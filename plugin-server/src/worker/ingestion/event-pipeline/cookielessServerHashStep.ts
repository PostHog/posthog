import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as siphashDouble from '@posthog/siphash/lib/siphash-double'
import { DateTime } from 'luxon'
import { Counter } from 'prom-client'
import { getDomain } from 'tldts'

import { cookielessRedisErrorCounter, eventDroppedCounter } from '../../../main/ingestion-queues/metrics'
import { runInstrumentedFunction } from '../../../main/utils'
import { CookielessConfig, CookielessServerHashMode, Hub } from '../../../types'
import { ConcurrencyController } from '../../../utils/concurrencyController'
import { DB } from '../../../utils/db/db'
import { RedisOperationError } from '../../../utils/db/error'
import { now } from '../../../utils/now'
import {
    base64StringToUint32ArrayLE,
    createRandomUint32x4,
    uint32ArrayLEToBase64String,
    UUID7,
} from '../../../utils/utils'
import { toStartOfDayInTimezone, toYearMonthDayInTimezone } from '../timestamps'

/* ---------------------------------------------------------------------
 * This pipeline step is used to get the distinct id and session id for events that are using the cookieless server hash mode.
 * At the most basic level, the new distinct id is hash(daily_salt + team_id + ip + root_domain + user_agent).

 * Why use a hash-based distinct id rather than a cookie-based one?
 * - Under GDPR, customers would be required to get consent from their users to store analytics cookies. Many customers
 *   don't want to ask for this consent, and many users don't want to give it.
 * - Instead of using a cookie, we can find some stable properties of the user that are sent with every http request
 *   (ip, user agent, domain), and hash them. This hash can be used as a distinct id. In most cases this provides
 *   enough uniqueness, but if the customer wants to add any other data to their users' hashes, we provide the
 *   $cookieless_extra property for them to do so.
 * - We add a salt to the hash so that is not considered PII and is not possible to reverse. We throw away the salt when
 *   it is no longer valid.
 *
 * The daily salt is a 128-bit random value that is stored in redis. We use the calendar day of the event in the user's
 * timezone to determine which salt to use. This means that we have more than one salt in use at any point, but once
 * a salt is expired, it is deleted, and it is impossible to recover the PII that was used to generate the hash.
 *
 * Due to ingestion lag and time zones, we allow creating the hash for a calendar day that is different to the current
 * UTC calendar day, provided somewhere in the world could be in that calendar day, with some additional buffer in the
 * past for ingestion lag.
 *
 * There are 2 modes of operation for this pipeline step, one is fully stateless between events and does not touch redis
 * beyond saving and loading the salt. This mode cannot support $identify and $alias events, and does not support
 * session timeout. There is one session per day per user, regardless of any period of inactivity.
 *
 * The other mode is stateful, and uses redis to store the session state and prevent self-collisions when using
 * $identify events.
 *
 * Stateless mode:
 *
 * The distinct id is a prefix + the base64 representation of the hash. The session ID is a UUIDv7, that uses some of
 * the bytes of the hash as the random part, and the timestamp of the start of the day as the timestamp part.
 *
 * Stateful mode:
 *
 * The session ID is a UUIDv7 that's stored in redis, using the timestamp of the first event of the session as the
 * timestamp part of the UUID. We implement our own session inactivity system rather than using redis TTLs, as the
 * session inactivity period is 30 minutes, and it's not impossible for us to have well over 30 minutes of ingestion lag.
 *
 * To ensure that a user that logs in and out doesn't collide with themselves, we store the set of identify event UUIDs
 * in redis against the base hash value, and use the number of identifies for that hash to calculate the final hash value.
 * The exact number we append is the number of identifies that happened before this user called identify, which will
 * mean adjusting the number based on whether the event was pre or post identify, or was itself the identify event.
 */

const TIMEZONE_FALLBACK = 'UTC'
export const COOKIELESS_SENTINEL_VALUE = '$posthog_cookieless'
export const COOKIELESS_MODE_FLAG_PROPERTY = '$cookieless_mode'
export const COOKIELESS_EXTRA_HASH_CONTENTS_PROPERTY = '$cookieless_extra'
const MAX_NEGATIVE_TIMEZONE_HOURS = 12
const MAX_POSITIVE_TIMEZONE_HOURS = 14

export class CookielessSaltManager {
    private readonly db: DB
    private readonly config: CookielessConfig
    private readonly localSaltMap: Record<string, Uint32Array> = {}
    private readonly mutex = new ConcurrencyController(1)
    private cleanupInterval: NodeJS.Timeout | null = null

    constructor(db: DB, config: CookielessConfig) {
        this.db = db
        this.config = config
        // Periodically delete expired salts from the local cache. Note that this doesn't delete them from redis, but
        // that's handled by using redis TTLs. Deleting these salts is what allows us to use the hash of PII data in a
        // non PII way. Of course, these are also deleted when the node process restarts.
        this.cleanupInterval = setInterval(this.deleteExpiredLocalSalts, config.deleteExpiredLocalSaltsIntervalMs)
        // Call unref on the timer object, so that it doesn't prevent node from exiting.
        this.cleanupInterval.unref()
    }

    getSaltForDay(yyyymmdd: string, timestampMs: number): Promise<Uint32Array> {
        if (!isCalendarDateValid(yyyymmdd)) {
            throw new Error('Date is out of range')
        }

        // see if we have it locally
        if (this.localSaltMap[yyyymmdd]) {
            return Promise.resolve(this.localSaltMap[yyyymmdd])
        }

        // get the salt for the day from redis, but only do this once for this node process
        return this.mutex.run({
            fn: async (): Promise<Uint32Array> => {
                // check if we got the salt while waiting for the mutex
                if (this.localSaltMap[yyyymmdd]) {
                    return this.localSaltMap[yyyymmdd]
                }

                // try to get it from redis instead
                const saltBase64 = await this.db.redisGet<string | null>(
                    `cookieless_salt:${yyyymmdd}`,
                    null,
                    'cookielessServerHashStep'
                )
                if (saltBase64) {
                    cookielessCacheHitCounter.labels({ operation: 'getSaltForDay', day: yyyymmdd }).inc()
                    const salt = base64StringToUint32ArrayLE(saltBase64)
                    this.localSaltMap[yyyymmdd] = salt
                    return salt
                }
                cookielessCacheMissCounter.labels({ operation: 'getSaltForDay', day: yyyymmdd }).inc()

                // try to write a new one to redis, but don't overwrite
                const newSaltParts = createRandomUint32x4()
                const setResult = await this.db.redisSetNX(
                    `cookieless_salt:${yyyymmdd}`,
                    uint32ArrayLEToBase64String(newSaltParts),
                    'cookielessServerHashStep',
                    this.config.saltTtlSeconds
                )
                if (setResult === 'OK') {
                    this.localSaltMap[yyyymmdd] = newSaltParts
                    return newSaltParts
                }

                // if we couldn't write, it means that it exists in redis already
                const saltBase64Retry = await this.db.redisGet<string | null>(
                    `cookieless_salt:${yyyymmdd}`,
                    null,
                    'cookielessServerHashStep'
                )
                if (!saltBase64Retry) {
                    throw new Error('Failed to get salt from redis')
                }

                const salt = base64StringToUint32ArrayLE(saltBase64Retry)
                this.localSaltMap[yyyymmdd] = salt

                return salt
            },
            priority: timestampMs,
        })
    }

    deleteExpiredLocalSalts = () => {
        for (const key in this.localSaltMap) {
            if (!isCalendarDateValid(key)) {
                delete this.localSaltMap[key]
            }
        }
    }

    deleteAllLocalSalts(): void {
        for (const key in this.localSaltMap) {
            delete this.localSaltMap[key]
        }
    }

    shutdown(): void {
        if (this.cleanupInterval) {
            clearInterval(this.cleanupInterval)
            this.cleanupInterval = null
        }
        this.deleteAllLocalSalts()
    }
}

export async function cookielessServerHashStep(hub: Hub, event: PluginEvent): Promise<[PluginEvent | undefined]> {
    // if events aren't using this mode, skip all processing
    if (!event.properties?.[COOKIELESS_MODE_FLAG_PROPERTY]) {
        return [event]
    }

    // if the killswitch is enabled, drop the event
    if (hub.cookielessConfig.disabled) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'cookieless_disabled_killswitch',
            })
            .inc()
        return [undefined]
    }

    try {
        return await runInstrumentedFunction({
            func: () => cookielessServerHashStepInner(hub, event as PluginEvent & { properties: Properties }),
            statsKey: 'cookieless.process_event',
        })
    } catch (e) {
        // Drop the event if there are any errors.
        // We fail close here as Cookieless is a new feature, not available for general use yet, and we don't want any
        // errors to interfere with the processing of other events.
        // Fail close rather than open, as events in this mode relying on this processing step to remove Personal Data.
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'cookieless_error_fail_close',
            })
            .inc()

        if (e instanceof RedisOperationError) {
            cookielessRedisErrorCounter.labels({
                operation: e.operation,
            })
        }

        return [undefined]
    }
}

async function cookielessServerHashStepInner(
    hub: Hub,
    event: PluginEvent & { properties: Properties }
): Promise<[PluginEvent | undefined]> {
    const config = hub.cookielessConfig

    // if the team isn't allowed to use this mode, drop the event
    const team = await hub.teamManager.getTeamForEvent(event)
    if (!team?.cookieless_server_hash_mode) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'cookieless_disabled_team',
            })
            .inc()
        return [undefined]
    }
    const teamTimeZone = team.timezone

    const timestamp = event.timestamp ?? event.sent_at ?? event.now

    // drop some events that aren't valid in this mode
    if (!timestamp) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'cookieless_no_timestamp',
            })
            .inc()
        return [undefined]
    }
    const { $session_id: sessionId, $device_id: deviceId } = event.properties
    if (sessionId != null || deviceId != null) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: sessionId != null ? 'cookieless_with_session_id' : 'cookieless_with_device_id',
            })
            .inc()
        return [undefined]
    }

    if (event.event === '$create_alias' || event.event === '$merge_dangerously') {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'cookieless_unsupported_event_type',
            })
            .inc()
        return [undefined]
    }

    // if it's an identify event, it must have the sentinel distinct id
    if (event.event === '$identify' && event.properties['$anon_distinct_id'] !== COOKIELESS_SENTINEL_VALUE) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: 'cookieless_missing_sentinel',
            })
            .inc()
        return [undefined]
    }

    const {
        userAgent,
        ip,
        host,
        timezone: eventTimeZone,
        timestampMs,
        teamId,
        hashExtra,
    } = getProperties(event, timestamp)
    if (!userAgent || !ip || !host) {
        eventDroppedCounter
            .labels({
                event_type: 'analytics',
                drop_cause: !userAgent
                    ? 'cookieless_missing_ua'
                    : !ip
                    ? 'cookieless_missing_ip'
                    : 'cookieless_missing_host',
            })
            .inc()
        return [undefined]
    }

    if (
        team.cookieless_server_hash_mode === CookielessServerHashMode.Stateless ||
        hub.cookielessConfig.forceStatelessMode
    ) {
        if (event.event === '$identify' || event.distinct_id !== COOKIELESS_SENTINEL_VALUE) {
            // identifies and post-identify events are not valid in the stateless mode, drop the event
            eventDroppedCounter
                .labels({
                    event_type: 'analytics',
                    drop_cause: 'cookieless_stateless_unsupported_identify',
                })
                .inc()
            return [undefined]
        }

        const hashValue = await doHash(hub, {
            timestampMs,
            eventTimeZone,
            teamTimeZone,
            teamId,
            ip,
            host,
            userAgent,
            hashExtra,
        })
        const distinctId = hashToDistinctId(hashValue)
        const newEvent = {
            ...event,
            distinct_id: distinctId,
            properties: {
                ...event.properties,
                $device_id: distinctId,
                $session_id: createStatelessSessionId(timestampMs, eventTimeZone, teamTimeZone, hashValue),
            },
        }
        stripPIIProperties(newEvent)
        return [newEvent]
    } else {
        // TRICKY: if a user were to log in and out, to avoid collisions, we would want a different hash value, so we store the set of identify event uuids for identifies
        // ASSUMPTION: all events are processed in order, for this to happen we need them to be in the same kafka topic at this point

        // Find the base hash value, before we take the number of identifies into account
        const baseHashValue = await doHash(hub, {
            timestampMs,
            eventTimeZone,
            teamTimeZone,
            teamId,
            ip,
            host,
            userAgent,
            hashExtra,
        })

        const newEvent = { ...event }
        const newProperties: Properties = { ...event.properties, $distinct_id: undefined }

        newProperties['$device_id'] = hashToDistinctId(baseHashValue)
        const identifiesRedisKey = getRedisIdentifiesKey(baseHashValue, teamId)

        let hashValue: Uint32Array
        if (event.event === '$identify') {
            // identify event, so the anon_distinct_id must be the sentinel and needs to be replaced

            // add this identify event id to redis
            const numIdentifies = await hub.db.redisSAddAndSCard(identifiesRedisKey, event.uuid)

            // we want the number of identifies that happened before this one
            hashValue = await doHash(hub, {
                timestampMs,
                eventTimeZone,
                teamTimeZone,
                teamId,
                ip,
                host,
                userAgent,
                n: numIdentifies - 1,
                hashExtra,
            })

            // set the distinct id to the new hash value
            newProperties['$anon_distinct_id'] = hashToDistinctId(hashValue)
        } else if (event.distinct_id === COOKIELESS_SENTINEL_VALUE) {
            const numIdentifies = await hub.db.redisSCard(identifiesRedisKey)
            hashValue = await doHash(hub, {
                timestampMs,
                eventTimeZone,
                teamTimeZone,
                teamId,
                ip,
                host,
                userAgent,
                n: numIdentifies,
                hashExtra,
            })
            // event before identify has been called, distinct id is the sentinel and needs to be replaced
            newEvent.distinct_id = hashToDistinctId(hashValue)
        } else {
            const numIdentifies = await hub.db.redisSCard(identifiesRedisKey)

            // this event is after identify has been called, so subtract 1 from the numIdentifies
            hashValue = await doHash(hub, {
                timestampMs,
                eventTimeZone,
                teamTimeZone,
                teamId,
                ip,
                host,
                userAgent,
                n: numIdentifies - 1,
                hashExtra,
            })
        }

        const sessionRedisKey = getRedisSessionsKey(hashValue, teamId)
        // do we have a session id for this user already?
        const sessionInfoBuffer = await hub.db.redisGetBuffer(sessionRedisKey, 'cookielessServerHashStep')
        let sessionState = sessionInfoBuffer ? bufferToSessionState(sessionInfoBuffer) : undefined

        // if not, or the TTL has expired, create a new one. Don't rely on redis TTL, as ingestion lag could approach the 30-minute session inactivity timeout
        if (!sessionState || timestampMs - sessionState.lastActivityTimestamp > config.sessionInactivityMs) {
            const sessionId = new UUID7(timestampMs)
            sessionState = { sessionId: sessionId, lastActivityTimestamp: timestampMs }
            await hub.db.redisSetBuffer(
                sessionRedisKey,
                sessionStateToBuffer(sessionState),
                'cookielessServerHashStep',
                config.sessionTtlSeconds
            )
        } else {
            // otherwise, update the timestamp
            await hub.db.redisSetBuffer(
                sessionRedisKey,
                sessionStateToBuffer({ sessionId: sessionState.sessionId, lastActivityTimestamp: timestampMs }),
                'cookielessServerHashStep',
                config.sessionTtlSeconds
            )
        }

        newProperties['$session_id'] = sessionState.sessionId.toString()

        newEvent.properties = newProperties
        stripPIIProperties(newEvent)
        return [newEvent]
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
    hashExtra: string | undefined
} {
    const userAgent = event.properties?.['$raw_user_agent']
    const ip = event.properties?.['$ip']
    const host = event.properties?.['$host']
    const timezone = event.properties?.['$timezone']
    const hashExtra = event.properties?.[COOKIELESS_EXTRA_HASH_CONTENTS_PROPERTY]
    const timestampMs = DateTime.fromISO(timestamp).toMillis()
    const teamId = event.team_id

    return { userAgent, ip, host, timezone, timestampMs, teamId, hashExtra }
}

export async function doHash(
    hub: Hub,
    {
        timestampMs,
        eventTimeZone,
        teamTimeZone,
        teamId,
        ip,
        host,
        userAgent,
        n = 0,
        hashExtra = '',
    }: {
        timestampMs: number
        eventTimeZone: string | undefined
        teamTimeZone: string
        teamId: number
        ip: string
        host: string
        userAgent: string
        n?: number
        hashExtra?: string
    }
) {
    const yyyymmdd = toYYYYMMDDInTimezoneSafe(timestampMs, eventTimeZone, teamTimeZone)
    const salt = await hub.cookielessSaltManager.getSaltForDay(yyyymmdd, timestampMs)
    const rootDomain = getDomain(host) || host
    return siphashDouble.hash(
        salt,
        `${teamId.toString()}-${ip}-${rootDomain}-${userAgent}-${n}-${hashExtra.slice(0, 100)}`
    )
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

    const isGteMinimum = nowUTC >= startOfDayMinus12
    const isLtMaximum = nowUTC < endOfDayPlus14

    // Check if the current UTC time falls within this range
    return isGteMinimum && isLtMaximum
}

export function hashToDistinctId(hash: Uint32Array): string {
    // add a prefix so that we can recognise one of these in the wild
    return 'cookieless_' + uint32ArrayLEToBase64String(hash).replace(/=+$/, '')
}

export function getRedisIdentifiesKey(hash: Uint32Array, teamId: number): string {
    // assuming 6 digits for team id, this is 6 + 2 + 6 + 24 = 38 characters
    // cklsi = cookieless identifies
    return `cklsi:${teamId}:${uint32ArrayLEToBase64String(hash)}`
}

export function getRedisSessionsKey(hash: Uint32Array, teamId: number): string {
    // assuming 6 digits for team id, this is 6 + 2 + 6 + 24 = 38 characters
    // cklss = cookieless sessions
    return `cklss:${teamId}:${uint32ArrayLEToBase64String(hash)}`
}

export function toYYYYMMDDInTimezoneSafe(
    timestamp: number,
    eventTimeZone: string | undefined,
    teamTimeZone: string
): string {
    let dateObj: { year: number; month: number; day: number } | undefined
    if (eventTimeZone) {
        try {
            dateObj = toYearMonthDayInTimezone(timestamp, eventTimeZone)
        } catch {
            // pass
        }
    }
    if (!dateObj) {
        try {
            dateObj = toYearMonthDayInTimezone(timestamp, teamTimeZone)
        } catch {
            dateObj = toYearMonthDayInTimezone(timestamp, TIMEZONE_FALLBACK)
        }
    }
    return `${dateObj.year}-${dateObj.month.toString().padStart(2, '0')}-${dateObj.day.toString().padStart(2, '0')}`
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

export function stripPIIProperties(event: PluginEvent) {
    if (event.properties) {
        // we use these properties in the hash, but they should not be written to disk if explicit consent was not given
        delete event.properties['$ip']
        delete event.properties['$raw_user_agent']
        delete event.properties[COOKIELESS_EXTRA_HASH_CONTENTS_PROPERTY]
    }
    event.ip = null
    return event
}

interface SessionState {
    sessionId: UUID7 // 16 bytes
    // 8 bytes, LE uint64 (I couldn't bring myself to store a timestamp as a double, even in JS where everything is a double)
    // log2(Date.now()) ~= 40, so 52 bits of mantissa *would* be fine, I'm just being an unreasonable pedant
    lastActivityTimestamp: number
}
export function bufferToSessionState(buffer: Buffer): SessionState {
    // the first 16 bytes are the session id
    const sessionId = new UUID7(buffer.subarray(0, 16))
    // the next 8 bytes are the last activity timestamp
    const lastActivityTimestamp = Number(buffer.readBigUInt64LE(16))

    return { sessionId, lastActivityTimestamp }
}

export function sessionStateToBuffer({ sessionId, lastActivityTimestamp }: SessionState): Buffer {
    const buffer = Buffer.alloc(24)
    buffer.set(sessionId.array, 0)
    buffer.writeBigUInt64LE(BigInt(lastActivityTimestamp), 16)
    return buffer
}

const cookielessCacheHitCounter = new Counter({
    name: 'cookieless_salt_cache_hit',
    help: 'Number of local cache hits for cookieless salt',
    labelNames: ['operation', 'day'],
})

const cookielessCacheMissCounter = new Counter({
    name: 'cookieless_salt_cache_miss',
    help: 'Number of local cache misses for cookieless salt',
    labelNames: ['operation', 'day'],
})
