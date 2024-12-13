import { PluginEvent } from '@posthog/plugin-scaffold'
import * as crypto from 'crypto'
import { DateTime } from 'luxon'
import * as siphashDouble from 'siphash/lib/siphash-double'
import { getDomain } from 'tldts'

import { ConcurrencyController } from '../../../utils/concurrencyController'
import { DB } from '../../../utils/db/db'
import { now } from '../../../utils/now'
import { UUID7 } from '../../../utils/utils'
import { toStartOfDayInTimezone, toYearMonthDayInTimezone } from '../timestamps'
import { EventPipelineRunner } from './runner'

//---------------------------------------------------------------------
// This pipeline step is used to get the distinct id and session id for events that are using the cookieless server hash mode.
// At the most basic level, the new distinct id is hash(daily_salt + team_id + ip + root_domain + user_agent).

// The session ID is a UUIDv7 that's stored in redis, using the timestamp of the first event of the session as the
// timestamp part of the UUID. We implement our own session inactivity system rather than using redis TTLs, as the
// session inactivity period is 30 minutes, and it's not impossible for us to have well over 30 minutes of ingestion lag.

// The daily salt is a 128-bit random value that is stored in redis. We use the calendar day of the event in the user's
// timezone to determine which salt to use. This means that we have more than one salt in use at any point, but once
// a salt is expired, it is deleted, and it is impossible to recover the PII that was used to generate the hash.

// Due to ingestion lag and time zones, we allow creating the hash for a calendar day that is different to the current
// UTC calendar day, provided somewhere in the world could be in that calendar day, with some additional buffer in the
// past for ingestion lag.

// To ensure that a user that logs in and out doesn't collide with themselves, we store the set of identify event UUIDs
// in redis against the base hash value, and use the number of identifies for that hash to calculate the final hash value.
// The exact number we append is the number of identifies that happened before this user called identify, which will
// mean adjusting the number based on whether the event was pre or post identify, or was itself the identify event.

const TIMEZONE_FALLBACK = 'UTC'
const COOKIELESS_SENTINEL_VALUE = '$posthog_cklsh'
const COOKIELESS_MODE_FLAG_PROPERTY = '$cklsh_mode'
const MAX_NEGATIVE_TIMEZONE_HOURS = 12
const MAX_POSITIVE_TIMEZONE_HOURS = 14
const MAX_INGESTION_LAG_HOURS = 24
const SALT_TTL_SECONDS =
    (MAX_POSITIVE_TIMEZONE_HOURS + MAX_NEGATIVE_TIMEZONE_HOURS + MAX_INGESTION_LAG_HOURS + 24) * 60 * 60
const SESSION_TTL_SECONDS = 60 * 60 * 24
const IDENTIFIES_TTL_SECONDS = 60 * 60 * 24
const DELETE_EXPIRED_SALTS_INTERVAL_MS = 60 * 60 * 1000
const DO_SIMPLE_PIPELINE_STEP = true

export async function cookielessServerHashStep(
    runner: EventPipelineRunner,
    event: PluginEvent
): Promise<[PluginEvent | undefined]> {
    // if events aren't using this mode, skip all processing
    if (!event.properties?.[COOKIELESS_MODE_FLAG_PROPERTY]) {
        return [event]
    }

    // if the team isn't allowed to use this mode, drop the event
    const team = await runner.hub.teamManager.getTeamForEvent(event)
    if (!team?.cookieless_server_hash_opt_in) {
        // TODO log
        return [undefined]
    }
    const teamTimeZone = team.timezone

    const timestamp = event.timestamp ?? event.sent_at ?? event.now

    // drop some events that aren't valid in this mode
    if (!timestamp) {
        // TODO log
        return [undefined]
    }
    const { $session_id: sessionId, $device_id: deviceId } = event.properties
    if (sessionId != null || deviceId != null) {
        // TODO log
        return [undefined]
    }

    if (event.event === '$alias') {
        // TODO support these
        return [undefined]
    }

    // if it's an identify event, it must have the sentinel distinct id
    if (event.event === '$identify' && event.properties['$anon_distinct_id'] !== COOKIELESS_SENTINEL_VALUE) {
        // TODO log
        return [undefined]
    }

    const { userAgent, ip, host, timezone: eventTimeZone, timestampMs, teamId } = getProperties(event, timestamp)
    if (!userAgent || !ip || !host) {
        // TODO log
        return [undefined]
    }

    if (DO_SIMPLE_PIPELINE_STEP) {
        if (event.event === '$identify' || event.distinct_id !== COOKIELESS_SENTINEL_VALUE) {
            // identifies and post-identify events are not valid in the simple mode, drop the event
            return [undefined]
        }

        const hashValue = await doHash(runner.hub.db, {
            timestampMs,
            eventTimeZone,
            teamTimeZone,
            teamId,
            ip,
            host,
            userAgent,
        })
        const distinctId = hashToDistinctId(hashValue)
        event.distinct_id = distinctId
        event.properties['$device_id'] = distinctId
        event.properties['$session_id'] = createStatelessSessionId(timestampMs, eventTimeZone, teamTimeZone, hashValue)

        return [event]
    } else {
        // TRICKY: if a user were to log in and out, to avoid collisions, we would want a different hash value, so we store the set of identify event uuids for identifies
        // ASSUMPTION: all events are processed in order, for this to happen we need them to be in the same kafka topic at this point

        // Find the base hash value, before we take the number of identifies into account
        const baseHashValue = await doHash(runner.hub.db, {
            timestampMs,
            eventTimeZone,
            teamTimeZone,
            teamId,
            ip,
            host,
            userAgent,
        })
        event.properties['$device_id'] = hashToDistinctId(baseHashValue)
        const identifiesRedisKey = getRedisIdentifiesKey(baseHashValue, teamId)

        let hashValue: Uint32Array
        if (event.event === '$identify') {
            // identify event, so the anon_distinct_id must be the sentinel and needs to be replaced

            // add this identify event id to redis
            const numIdentifies = await runner.hub.db.redisSAddAndSCard(
                identifiesRedisKey,
                event.uuid,
                IDENTIFIES_TTL_SECONDS
            )

            // we want the number of identifies that happened before this one
            hashValue = await doHash(runner.hub.db, {
                timestampMs,
                eventTimeZone,
                teamTimeZone,
                teamId,
                ip,
                host,
                userAgent,
                n: numIdentifies - 1,
            })

            // set the distinct id to the new hash value
            event.properties[`$anon_distinct_id`] = hashToDistinctId(hashValue)
        } else if (event.distinct_id === COOKIELESS_SENTINEL_VALUE) {
            const numIdentifies = await runner.hub.db.redisSCard(identifiesRedisKey)
            hashValue = await doHash(runner.hub.db, {
                timestampMs,
                eventTimeZone,
                teamTimeZone,
                teamId,
                ip,
                host,
                userAgent,
                n: numIdentifies,
            })
            // event before identify has been called, distinct id is the sentinel and needs to be replaced
            event.distinct_id = hashToDistinctId(hashValue)
            event.properties[`$distinct_id`] = hashValue
        } else {
            const numIdentifies = await runner.hub.db.redisSCard(identifiesRedisKey)

            // this event is after identify has been called, so subtract 1 from the numIdentifies
            hashValue = await doHash(runner.hub.db, {
                timestampMs,
                eventTimeZone,
                teamTimeZone,
                teamId,
                ip,
                host,
                userAgent,
                n: numIdentifies - 1,
            })
        }

        const sessionRedisKey = getRedisSessionsKey(hashValue, teamId)
        // do we have a session id for this user already?
        // TODO optimise the value size here by using binary
        let sessionInfo = await runner.hub.db.redisGet<{ s: string; t: number } | null>(
            sessionRedisKey,
            null,
            'cookielessServerHashStep',
            {
                jsonSerialize: true,
            }
        )
        // if not, or the TTL has expired, create a new one. Don't rely on redis TTL, as ingestion lag could approach the 30-minute session inactivity timeout
        if (!sessionInfo || timestampMs - sessionInfo.t > 60 * 30 * 1000) {
            const sessionId = new UUID7(timestampMs).toString()
            sessionInfo = { s: sessionId, t: timestampMs }
            await runner.hub.db.redisSet(sessionRedisKey, sessionInfo, 'cookielessServerHashStep', SESSION_TTL_SECONDS)
        } else {
            // otherwise, update the timestamp
            await runner.hub.db.redisSet(
                sessionRedisKey,
                { s: sessionInfo.s, t: timestampMs },
                'cookielessServerHashStep',
                SESSION_TTL_SECONDS
            )
        }

        event.properties['$session_id'] = sessionInfo.s

        return [event]
    }
}

function getProperties(
    event: PluginEvent,
    timestamp: string
): {
    userAgent: string | undefined
    ip: string | undefined
    host: string | undefined
    timezone: string | undefined
    timestampMs: number
    teamId: number
} {
    const userAgent = event.properties?.['$raw_user_agent']
    const ip = event.properties?.['$ip']
    const host = event.properties?.['$host']
    const timezone = event.properties?.['$timezone']
    const timestampMs = DateTime.fromISO(timestamp).toMillis()
    const teamId = event.team_id

    return { userAgent, ip, host, timezone, timestampMs, teamId }
}

const localSaltMap: Record<string, Uint32Array> = {}
const mutex = new ConcurrencyController(1)

export async function getSaltForDay(
    db: DB,
    timestamp: number,
    eventTimeZone: string | undefined,
    teamtimeZone: string
): Promise<Uint32Array> {
    // get the day based on the timezone
    const { year, month, day } = toYearMonthDayInTimezoneSafe(timestamp, eventTimeZone, teamtimeZone)
    const yyyymmdd = `${year}-${month}-${day}`

    if (!isCalendarDateValid(yyyymmdd)) {
        throw new Error('Date is out of range')
    }

    // see if we have it locally
    if (localSaltMap[yyyymmdd]) {
        return localSaltMap[yyyymmdd]
    }

    // get the salt for the day from redis, but only do this once for this node process
    return mutex.run({
        fn: async (): Promise<Uint32Array> => {
            // check if we got the salt while waiting for the mutex
            if (localSaltMap[yyyymmdd]) {
                return localSaltMap[yyyymmdd]
            }

            // try to get it from redis instead
            const saltBase64 = await db.redisGet<string | null>(
                `cookieless_salt:${yyyymmdd}`,
                null,
                'cookielessServerHashStep'
            )
            if (saltBase64) {
                const salt = base64StringToUint32Array(saltBase64)
                localSaltMap[yyyymmdd] = salt
                return salt
            }

            // try to write a new one to redis, but don't overwrite
            const newSaltParts = createRandomUint32x4()
            const setResult = await db.redisSetNX(
                `cookieless_salt:${yyyymmdd}`,
                uint32ArrayToBase64String(newSaltParts),
                'cookielessServerHashStep',
                SALT_TTL_SECONDS
            )
            if (setResult === 'OK') {
                localSaltMap[yyyymmdd] = newSaltParts
                return newSaltParts
            }

            // if we couldn't write, it means that it exists in redis already
            const saltBase64Retry = await db.redisGet<string | null>(
                `cookieless_salt:${yyyymmdd}`,
                null,
                'cookielessServerHashStep'
            )
            if (!saltBase64Retry) {
                throw new Error('Failed to get salt from redis')
            }
            return base64StringToUint32Array(saltBase64Retry)
        },
        priority: timestamp,
    })
}

export function base64StringToUint32Array(base64: string): Uint32Array {
    return new Uint32Array(Buffer.from(base64, 'base64').buffer)
}
export function uint32ArrayToBase64String(uint32Array: Uint32Array): string {
    return Buffer.from(uint32Array.buffer).toString('base64')
}

export function createRandomUint32x4(): Uint32Array {
    const randomArray = new Uint32Array(4)
    crypto.webcrypto.getRandomValues(randomArray)
    return randomArray
}

export async function doHash(
    db: DB,
    {
        timestampMs,
        eventTimeZone,
        teamTimeZone,
        teamId,
        ip,
        host,
        userAgent,
        n = 0,
    }: {
        timestampMs: number
        eventTimeZone: string | undefined
        teamTimeZone: string
        teamId: number
        ip: string
        host: string
        userAgent: string
        n?: number
    }
) {
    const salt = await getSaltForDay(db, timestampMs, eventTimeZone, teamTimeZone)
    const rootDomain = getDomain(host) || host
    return siphashDouble.hash(salt, `${teamId.toString()}-${ip}-${rootDomain}-${userAgent}-${n}`)
}

export function isCalendarDateValid(yyyymmdd: string): boolean {
    // make sure that the date is not in the future, i.e. at least one timezone could plausibly be in this calendar day,
    // and not too far in the past (with some buffer for ingestion lag)
    const utcDate = new Date(`${yyyymmdd}T00:00:00Z`)

    // Current time in UTC
    const nowUTC = new Date(now())

    // Define the range of the calendar day in UTC
    const startOfDayMinus12 = new Date(utcDate)
    startOfDayMinus12.setUTCHours(-MAX_NEGATIVE_TIMEZONE_HOURS) // Start at UTC−12

    const endOfDayPlus14 = new Date(utcDate)
    endOfDayPlus14.setUTCHours(MAX_POSITIVE_TIMEZONE_HOURS + 24) // End at UTC+14

    // Check if the current UTC time falls within this range
    return nowUTC >= startOfDayMinus12 && nowUTC < endOfDayPlus14
}

export function hashToDistinctId(hash: Uint32Array): string {
    // add a prefix so that we can recognise one of these in the wild
    return 'cklsh_' + uint32ArrayToBase64String(hash).replace(/=+$/, '')
}

export function getRedisIdentifiesKey(hash: Uint32Array, teamId: number): string {
    // assuming 6 digits for team id, this is 8 + 2 + 6 + 24 = 40 characters
    return `cklshi:${teamId}:${uint32ArrayToBase64String(hash)}`
}

export function getRedisSessionsKey(hash: Uint32Array, teamId: number): string {
    // assuming 6 digits for team id, this is 8 + 2 + 6 + 24 = 40 characters
    return `cklshs:${teamId}:${uint32ArrayToBase64String(hash)}`
}

export function toYearMonthDayInTimezoneSafe(
    timestamp: number,
    eventTimeZone: string | undefined,
    teamTimeZone: string
): { year: number; month: number; day: number } {
    if (eventTimeZone) {
        try {
            return toYearMonthDayInTimezone(timestamp, eventTimeZone)
        } catch {
            // pass
        }
    }
    try {
        return toYearMonthDayInTimezone(timestamp, teamTimeZone)
    } catch {
        return toYearMonthDayInTimezone(timestamp, TIMEZONE_FALLBACK)
    }
}

export function toStartOfDayInTimezoneSafe(
    timestamp: number,
    eventTimeZone: string | undefined,
    teamTimeZone: string
): Date {
    if (eventTimeZone) {
        try {
            return toStartOfDayInTimezone(timestamp, eventTimeZone)
        } catch {
            // pass
        }
    }
    try {
        return toStartOfDayInTimezone(timestamp, teamTimeZone)
    } catch {
        return toStartOfDayInTimezone(timestamp, TIMEZONE_FALLBACK)
    }
}

export function createStatelessSessionId(
    timestamp: number,
    eventTimezone: string | undefined,
    teamTimeZone: string,
    hash: Uint32Array
): UUID7 {
    // A sessionId is a UUIDv7, which has a timestamp part and a random part. We need to find a deterministic way to
    // generate this ID whilst meeting the requirements of posthog session IDs
    // see https://posthog.com/docs/data/sessions#custom-session-ids

    // For the timestamp part, use the start of the day, in this user's timezone
    const timestampOfStartOfDay = toStartOfDayInTimezoneSafe(timestamp, eventTimezone, teamTimeZone).getTime()

    // For the random part, use the first 10 bytes of the hash (74 bits are actually used), as a way of ensuring
    // determinism with no state
    const fakeRandomBytes = Buffer.from(hash.buffer).subarray(0, 10)

    return new UUID7(timestampOfStartOfDay, fakeRandomBytes)
}

export function deleteExpiredSalts(): void {
    for (const key in localSaltMap) {
        if (!isCalendarDateValid(key)) {
            delete localSaltMap[key]
        }
    }
}

setInterval(deleteExpiredSalts, DELETE_EXPIRED_SALTS_INTERVAL_MS)
