import { PluginEvent } from '@posthog/plugin-scaffold'
import * as crypto from 'crypto'
import { DateTime } from 'luxon'
// @ts-expect-error no types
import * as siphashDouble from 'siphash/lib/siphash-double'
import { getDomain } from 'tldts'

import { ConcurrencyController } from '../../../utils/concurrencyController'
import { DB } from '../../../utils/db/db'
import { now } from '../../../utils/now'
import { UUID7 } from '../../../utils/utils'
import { EventPipelineRunner } from './runner'

const TIMEZONE_FALLBACK = 'UTC'
const SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID = '$sentinel_cookieless_server_hash'
const MAX_NEGATIVE_TIMEZONE_HOURS = 12
const MAX_POSITIVE_TIMEZONE_HOURS = 14
const MAX_INGESTION_LAG_HOURS = 24
const SALT_TTL_SECONDS =
    (MAX_POSITIVE_TIMEZONE_HOURS + MAX_NEGATIVE_TIMEZONE_HOURS + MAX_INGESTION_LAG_HOURS + 24) * 60 * 60
const SESSION_TTL_SECONDS = 60 * 60 * 24

//---------------------------------------------------------------------
// This pipeline step is used to get the distinct id and session id for events that are using the cookieless server hash mode.
// At the most basic level, the new distinct id is hash(daily_salt + team_id + ip + root_domain + user_agent).

// The daily salt is a 128-bit random value that is stored in redis. We use the calendar day of the event in the user's
// timezone to determine which salt to use. This means that we have more than one salt in use at any point, but once
// a salt is expired, it is deleted, and it is impossible to recover the PII that was used to generate the hash.

// Due to ingestion lag and time zones, we allow creating the hash for a calendar day in the future (compared to UTC)
// provided somewhere in the world could be in that timezone. We also allow creating the hash for days in the past,
// again taking timezones into account, and an extra buffer for ingestion lag.

// There's an edge case where a user could log in and out in the same day, and we want to avoid collisions, so we store
// the set of identify event uuids, an suffix this number to the hash value to create the distinct id.

export async function cookielessServerHashStep(
    runner: EventPipelineRunner,
    event: PluginEvent
): Promise<[PluginEvent | undefined]> {
    // if events aren't using this mode, skip all processing
    if (event.properties?.['$device_id'] !== SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID) {
        return [event]
    }
    // if the team isn't using this mode, skip all processing
    // const team = await runner.hub.teamManager.getTeamForEvent(event)
    // if (!team?.cookieless_server_hash_opt_in) {
    //     // TODO log
    //     return [event]
    // }

    const timestamp = event.timestamp ?? event.sent_at ?? event.now

    // drop some events that aren't valid in this mode
    if (!timestamp) {
        // TODO log
        return [undefined]
    }
    const sessionId = event.properties['$session_id']
    if (sessionId !== SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID) {
        // TODO log
        return [undefined]
    }
    // if it's an identify event, it must have the sentinel distinct id
    if (
        event.event === '$identify' &&
        event.properties['$anon_distinct_id'] !== SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID
    ) {
        // TODO log
        return [undefined]
    }

    const { userAgent, ip, host, timezone, timestampMs, teamId } = getProperties(event, timestamp)
    if (!userAgent || !ip || !host) {
        // TODO log
        return [undefined]
    }

    const baseHashValue = await doHash(runner.hub.db, timestampMs, timezone, teamId, ip, host, userAgent)
    event.properties['$device_id'] = baseHashValue

    // TRICKY: if a user were to log in and out, to avoid collisions, we would want a different hash value, so we store the set of identify event uuids for identifies
    // ASSUMPTION: all events are processed in order, and are processed exactly once
    const identifiesRedisKey = `cookieless_i:${baseHashValue}`
    // how many identifies have happened with that hash value?
    const numIdentifies = await runner.hub.db.redisSCard(identifiesRedisKey)
    let hashValue: string

    if (event.event === '$identify') {
        // identify event, so the anon_distinct_id must be the sentinel and needs to be replaced

        // add this identify event id to redis
        const added = await runner.hub.db.redisSAdd(identifiesRedisKey, event.uuid)
        await runner.hub.db.redisExpire(identifiesRedisKey, SESSION_TTL_SECONDS) // TODO this is the max but could be less if we calculated how far away midnight is

        // we want the number of identifies excluding this one, but we need to think about idempotency. Redis will have
        // returned 1 if the event was added, and 0 if it was already there. If it was already there, we need to subtract 1
        const numIdentifies2 = numIdentifies + (added ? 0 : -1)

        hashValue = `${baseHashValue}_${numIdentifies2}`

        // set the distinct id to the new hash value
        event.properties[`$anon_distinct_id`] = hashValue
    } else if (event.distinct_id === SENTINEL_COOKIELESS_SERVER_HASH_DISTINCT_ID) {
        hashValue = `${baseHashValue}_${numIdentifies}`
        // event before identify has been called, distinct id is the sentinel and needs to be replaced
        event.distinct_id = hashValue
        event.properties[`$distinct_id`] = hashValue
    } else {
        // event after identify has been called, so subtract 1 from the numIdentifies
        hashValue = `${baseHashValue}_${numIdentifies - 1}`
    }

    const sessionRedisKey = `cookieless_s:${hashValue}`
    // do we have a session id for this user already?
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

function getProperties(
    event: PluginEvent,
    timestamp: string
): {
    userAgent: string | undefined
    ip: string | undefined
    host: string | undefined
    timezone: string
    timestampMs: number
    teamId: number
} {
    const userAgent = event.properties?.['$raw_user_agent']
    const ip = event.properties?.['$ip']
    const host = event.properties?.['$host']
    const timezone = event.properties?.['$timezone'] || TIMEZONE_FALLBACK
    const timestampMs = DateTime.fromISO(timestamp).toMillis()
    const teamId = event.team_id

    return { userAgent, ip, host, timezone, timestampMs, teamId }
}

const localSaltMap: Record<string, Uint32Array> = {}
const mutex = new ConcurrencyController(1)

export async function getSaltForDay(db: DB, timestamp: number, timeZone: string): Promise<Uint32Array> {
    // get the day based on the timezone
    const parts = new Intl.DateTimeFormat('en', {
        timeZone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).formatToParts(new Date(timestamp))
    const year = parts.find((part) => part.type === 'year')?.value
    const month = parts.find((part) => part.type === 'month')?.value
    const day = parts.find((part) => part.type === 'day')?.value
    const yyyymmdd = `${year}-${month}-${day}`

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

            // looks like we'll need to create a new one, but check the date is within range
            if (!isCalendarDateValid(yyyymmdd)) {
                throw new Error('Date is out of range')
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
    timestamp: number,
    timezone: string,
    teamId: number,
    ip: string,
    host: string,
    userAgent: string
) {
    const salt = await getSaltForDay(db, timestamp, timezone)
    const rootDomain = getDomain(host) || host
    // use the 128-bit version of siphash to get the result, with a stripe-style prefix, so we can see what these ids are when debugging
    return 'cklsh_' + siphashDouble.hash_hex(salt, `${teamId.toString()}-${ip}-${rootDomain}-${userAgent}`)
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

export function deleteExpiredSalts(): void {
    for (const key in localSaltMap) {
        if (!isCalendarDateValid(key)) {
            delete localSaltMap[key]
        }
    }
}
