import { randomBytes } from 'crypto'
import { Pool as GenericPool } from 'generic-pool'
import Redis from 'ioredis'
import { parse } from 'ipaddr.js'
import { DateTime } from 'luxon'
import { isIPv6 } from 'net'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'
import { getDomain } from 'tldts'

import { PluginEvent, Properties } from '@posthog/plugin-scaffold'
import * as siphashDouble from '@posthog/siphash/lib/siphash-double'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { cookielessRedisErrorCounter, eventDroppedCounter } from '../../main/ingestion-queues/metrics'
import {
    CookielessServerHashMode,
    EventHeaders,
    IncomingEventWithTeam,
    PipelineEvent,
    PluginsServerConfig,
    Team,
} from '../../types'
import { ConcurrencyController } from '../../utils/concurrencyController'
import { RedisOperationError } from '../../utils/db/error'
import { TeamManager } from '../../utils/team-manager'
import { UUID7, bufferToUint32ArrayLE, uint32ArrayLEToBuffer } from '../../utils/utils'
import { compareTimestamps } from '../../worker/ingestion/timestamp-comparison'
import { toStartOfDayInTimezone, toYearMonthDayInTimezone } from '../../worker/ingestion/timestamps'
import { PipelineResult, drop, ok } from '../pipelines/results'
import { RedisHelpers } from './redis-helpers'

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

interface CookielessConfig {
    disabled: boolean
    forceStatelessMode: boolean
    deleteExpiredLocalSaltsIntervalMs: number
    identifiesTtlSeconds: number
    sessionTtlSeconds: number
    saltTtlSeconds: number
    timestampLoggingSampleRate: number
    sessionInactivityMs: number
}

export class CookielessManager {
    public readonly redisHelpers: RedisHelpers
    public readonly config: CookielessConfig

    private readonly localSaltMap: Record<string, Buffer> = {}
    private readonly mutex = new ConcurrencyController(1)
    private cleanupInterval: NodeJS.Timeout | null = null

    constructor(
        config: PluginsServerConfig,
        redis: GenericPool<Redis.Redis>,
        private teamManager: TeamManager
    ) {
        this.config = {
            disabled: config.COOKIELESS_DISABLED,
            forceStatelessMode: config.COOKIELESS_FORCE_STATELESS_MODE,
            deleteExpiredLocalSaltsIntervalMs: config.COOKIELESS_DELETE_EXPIRED_LOCAL_SALTS_INTERVAL_MS,
            sessionTtlSeconds: config.COOKIELESS_SESSION_TTL_SECONDS,
            saltTtlSeconds: config.COOKIELESS_SALT_TTL_SECONDS,
            sessionInactivityMs: config.COOKIELESS_SESSION_INACTIVITY_MS,
            identifiesTtlSeconds: config.COOKIELESS_IDENTIFIES_TTL_SECONDS,
            timestampLoggingSampleRate: config.TIMESTAMP_COMPARISON_LOGGING_SAMPLE_RATE,
        }

        this.redisHelpers = new RedisHelpers(redis)
        // Periodically delete expired salts from the local cache. Note that this doesn't delete them from redis, but
        // that's handled by using redis TTLs. Deleting these salts is what allows us to use the hash of PII data in a
        // non PII way. Of course, these are also deleted when the node process restarts.
        this.cleanupInterval = setInterval(this.deleteExpiredLocalSalts, this.config.deleteExpiredLocalSaltsIntervalMs)
        // Call unref on the timer object, so that it doesn't prevent node from exiting.
        this.cleanupInterval.unref()
    }

    getSaltForDay(yyyymmdd: string, timestampMs: number): Promise<Buffer> {
        if (!isCalendarDateValid(yyyymmdd)) {
            throw new Error('Date is out of range')
        }

        // see if we have it locally
        if (this.localSaltMap[yyyymmdd]) {
            return Promise.resolve(this.localSaltMap[yyyymmdd])
        }

        // get the salt for the day from redis, but only do this once for this node process
        return this.mutex.run({
            fn: async (): Promise<Buffer> => {
                // check if we got the salt while waiting for the mutex
                if (this.localSaltMap[yyyymmdd]) {
                    return this.localSaltMap[yyyymmdd]
                }

                // try to get it from redis instead
                const saltBase64 = await this.redisHelpers.redisGet<string | null>(
                    `cookieless_salt:${yyyymmdd}`,
                    null,
                    'cookielessServerHashStep',
                    { jsonSerialize: false }
                )
                if (saltBase64) {
                    cookielessCacheHitCounter.labels({ operation: 'getSaltForDay', day: yyyymmdd }).inc()
                    const salt = Buffer.from(saltBase64, 'base64')
                    this.localSaltMap[yyyymmdd] = salt
                    return salt
                }
                cookielessCacheMissCounter.labels({ operation: 'getSaltForDay', day: yyyymmdd }).inc()

                // try to write a new one to redis, but don't overwrite
                const newSalt = randomBytes(16)
                const setResult = await this.redisHelpers.redisSetNX(
                    `cookieless_salt:${yyyymmdd}`,
                    newSalt.toString('base64'),
                    'cookielessServerHashStep',
                    this.config.saltTtlSeconds,
                    { jsonSerialize: false }
                )
                if (setResult === 'OK') {
                    this.localSaltMap[yyyymmdd] = newSalt
                    return newSalt
                }

                // if we couldn't write, it means that it exists in redis already
                const saltBase64Retry = await this.redisHelpers.redisGet<string | null>(
                    `cookieless_salt:${yyyymmdd}`,
                    null,
                    'cookielessServerHashStep',
                    { jsonSerialize: false }
                )
                if (!saltBase64Retry) {
                    throw new Error('Failed to get salt from redis')
                }

                const salt = Buffer.from(saltBase64Retry, 'base64')
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

    async doHashForDay({
        timestampMs,
        eventTimeZone,
        teamTimeZone,
        teamId,
        ip,
        host,
        userAgent,
        n = 0,
        hashExtra = '',
        hashCache,
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
        hashCache?: Record<string, Buffer>
    }) {
        const yyyymmdd = toYYYYMMDDInTimezoneSafe(timestampMs, eventTimeZone, teamTimeZone)
        const salt = await this.getSaltForDay(yyyymmdd, timestampMs)
        const rootDomain = extractRootDomain(host)
        return CookielessManager.doHash(salt, teamId, ip, rootDomain, userAgent, n, hashExtra, hashCache)
    }

    static doHash(
        salt: Buffer,
        teamId: number,
        ip: string,
        rootDomain: string,
        userAgent: string,
        n: number,
        hashExtra: string,
        hashCache?: Record<string, Buffer>
    ): Buffer {
        if (salt.length !== 16) {
            throw new Error('Salt must be 16 bytes')
        }

        const hashInputString = `${teamId.toString()}-${ip}-${rootDomain}-${userAgent}-${n}-${hashExtra.slice(0, 100)}`

        if (hashCache?.[hashInputString]) {
            return hashCache[hashInputString]
        }

        const array = siphashDouble.hash(bufferToUint32ArrayLE(salt), hashInputString)
        const buf = uint32ArrayLEToBuffer(array)

        if (hashCache) {
            hashCache[hashInputString] = buf
        }

        return buf
    }

    async doBatch(events: IncomingEventWithTeam[]): Promise<PipelineResult<IncomingEventWithTeam>[]> {
        if (this.config.disabled) {
            // cookieless is globally disabled, don't do any processing just drop all cookieless events
            return this.dropAllCookielessEvents(events, 'cookieless_globally_disabled')
        }
        try {
            return await instrumentFn(`cookieless-batch`, () => this.doBatchInner(events))
        } catch (e) {
            if (e instanceof RedisOperationError) {
                cookielessRedisErrorCounter.labels({
                    operation: e.operation,
                })
            }

            // Drop all cookieless events if there are any errors.
            // We fail close here as Cookieless is a new feature, not available for general use yet, and we don't want any
            // errors to interfere with the processing of other events.
            return this.dropAllCookielessEvents(events, 'cookieless-fail-close')
        }
    }

    private async doBatchInner(events: IncomingEventWithTeam[]): Promise<PipelineResult<IncomingEventWithTeam>[]> {
        const hashCache: Record<string, Buffer> = {}

        // Track results for each input event - initialize all as success, will be overwritten if dropped
        const results: PipelineResult<IncomingEventWithTeam>[] = events.map((event) => ok(event))

        // do a first pass just to extract properties and compute the base hash for stateful cookieless events
        const eventsWithStatus: EventWithStatus[] = []
        for (let i = 0; i < events.length; i++) {
            const { event, team, message, headers } = events[i]

            if (!event.properties?.[COOKIELESS_MODE_FLAG_PROPERTY]) {
                // push the event as is, we don't need to do anything with it, but preserve the ordering
                eventsWithStatus.push({ event, team, message, headers, originalIndex: i })
                continue
            }

            // only cookieless events past this point

            if (event.event === '$create_alias' || event.event === '$merge_dangerously') {
                // $alias and $merge events are not supported in cookieless mode, drop them
                eventDroppedCounter
                    .labels({
                        event_type: 'analytics',
                        drop_cause: 'cookieless_disallowed_event',
                    })
                    .inc()
                results[i] = drop('Event type not supported in cookieless mode')
                continue
            }
            if (
                event.event === '$identify' &&
                team.cookieless_server_hash_mode === CookielessServerHashMode.Stateless
            ) {
                // $identify events are not supported in stateless cookieless mode, drop them
                eventDroppedCounter
                    .labels({
                        event_type: 'analytics',
                        drop_cause: 'cookieless_stateless_disallowed_identify',
                    })
                    .inc()
                results[i] = drop('$identify not supported in stateless cookieless mode')
                continue
            }

            if (
                team.cookieless_server_hash_mode == null ||
                team.cookieless_server_hash_mode === CookielessServerHashMode.Disabled
            ) {
                // if the specific team doesn't have cookieless enabled, drop the event
                eventDroppedCounter
                    .labels({
                        event_type: 'analytics',
                        drop_cause: 'cookieless_team_disabled',
                    })
                    .inc()
                results[i] = drop('Cookieless disabled for team')
                continue
            }
            const timestamp = event.timestamp ?? event.sent_at ?? event.now

            if (!timestamp) {
                eventDroppedCounter
                    .labels({
                        event_type: 'analytics',
                        drop_cause: 'cookieless_no_timestamp',
                    })
                    .inc()
                results[i] = drop('Missing timestamp')
                continue
            }

            // Compare timestamp from headers with current parsing logic
            compareTimestamps(
                timestamp,
                headers,
                team.id,
                event.uuid,
                'cookieless_processing',
                this.config.timestampLoggingSampleRate
            )

            const {
                userAgent,
                ip,
                host,
                timestampMs,
                hashExtra,
                timezone: eventTimeZone,
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
                results[i] = drop(!userAgent ? 'Missing user agent' : !ip ? 'Missing IP' : 'Missing host')
                continue
            }

            const baseHash = await this.doHashForDay({
                timestampMs,
                eventTimeZone,
                teamTimeZone: team.timezone,
                teamId: team.id,
                ip,
                host,
                userAgent,
                hashExtra,
                hashCache,
            })

            eventsWithStatus.push({
                event,
                team,
                message,
                headers,
                originalIndex: i,
                firstPass: {
                    timestampMs,
                    eventTimeZone,
                    userAgent,
                    ip,
                    host,
                    hashExtra,
                    baseHash,
                },
            })
        }

        // early exit if we don't need to do anything
        if (!eventsWithStatus.some((e) => e.firstPass)) {
            return results
        }

        // Do a second pass to see what `identifiesRedisKey`s we need to load from redis for stateful events.
        // Fully process stateless events.
        const identifiesKeys = new Set<string>()
        for (const eventWithProcessing of eventsWithStatus) {
            const { team, firstPass } = eventWithProcessing
            if (!firstPass) {
                continue
            }

            if (team.cookieless_server_hash_mode === CookielessServerHashMode.Stateful) {
                const identifiesRedisKey = getRedisIdentifiesKey(firstPass.baseHash, team.id)
                identifiesKeys.add(identifiesRedisKey)
                firstPass.secondPass = { identifiesRedisKey }
            } else {
                const { baseHash, timestampMs, eventTimeZone } = firstPass
                const distinctId = hashToDistinctId(baseHash)
                const deviceId = baseHashToDeviceId(baseHash)
                const sessionId = createStatelessSessionId(timestampMs, eventTimeZone, team.timezone, baseHash)
                const newProperties: Properties = {
                    ...eventWithProcessing.event.properties,
                    $distinct_id: distinctId,
                    $device_id: deviceId,
                    $session_id: sessionId,
                }
                eventWithProcessing.event = stripPIIProperties({
                    ...eventWithProcessing.event,
                    distinct_id: distinctId,
                    properties: newProperties,
                })
                // the event is fully processed, no need to add create secondPass object
            }
        }

        // Fetch the identifies from redis and populate our in-memory cache
        const identifiesResult = await this.redisHelpers.redisSMembersMulti(
            Array.from(identifiesKeys.values()),
            'CookielessManagerBatch.prefetchIdentifies'
        )
        const identifiesCache: Record<string, IdentifiesCacheState> = Object.fromEntries(
            identifiesResult.map(([key, value]) => [
                key,
                {
                    identifyEventIds: new Set(value ?? []),
                    isDirty: false,
                },
            ])
        )

        // Do a third pass to set the distinct and device ID, and find the `sessionRedisKey`s we need to load from redis
        const sessionKeys = new Set<string>()
        for (const eventWithProcessing of eventsWithStatus) {
            const { event, team, firstPass } = eventWithProcessing
            if (!firstPass?.secondPass) {
                continue
            }
            const { timestampMs, eventTimeZone, ip, host, userAgent, hashExtra, secondPass } = firstPass
            const { identifiesRedisKey } = secondPass

            const identifiesCacheItem = identifiesCache[identifiesRedisKey]

            let n: number
            if (event.event === '$identify') {
                identifiesCacheItem.identifyEventIds.add(event.uuid)
                identifiesCacheItem.isDirty = true

                // identify, we want the number of identifies from before this event
                n = identifiesCacheItem.identifyEventIds.size - 1
            } else if (event.distinct_id === COOKIELESS_SENTINEL_VALUE) {
                // non-identify event
                n = identifiesCacheItem.identifyEventIds.size
            } else {
                // identified event, we want the number of identifies from before this user was identified
                n = identifiesCacheItem.identifyEventIds.size - 1
            }

            const hashValue = await this.doHashForDay({
                timestampMs,
                eventTimeZone,
                teamTimeZone: team.timezone,
                teamId: team.id,
                ip,
                host,
                userAgent,
                hashExtra,
                n,
            })
            const distinctId = hashToDistinctId(hashValue)
            const sessionRedisKey = getRedisSessionsKey(hashValue, team.id)
            sessionKeys.add(sessionRedisKey)
            secondPass.thirdPass = {
                distinctId,
                sessionRedisKey,
            }
        }

        // Load the session state from redis
        const sessionResult = await this.redisHelpers.redisMGetBuffer(
            Array.from(sessionKeys.values()),
            'CookielessManagerBatch.prefetchSessions'
        )
        const sessionCache: Record<string, SessionCacheState> = {}
        for (const [key, value] of sessionResult) {
            if (value) {
                sessionCache[key] = {
                    session: bufferToSessionState(value),
                    isDirty: false,
                }
            }
        }

        // Do a fourth (final) pass to update the events with the session state
        for (const eventWithProcessing of eventsWithStatus) {
            const { firstPass } = eventWithProcessing
            if (!firstPass?.secondPass?.thirdPass) {
                continue
            }
            const { timestampMs, baseHash } = firstPass
            const { sessionRedisKey, distinctId } = firstPass.secondPass.thirdPass
            const config = this.config

            let sessionCacheItem = sessionCache[sessionRedisKey]
            let sessionId: UUID7
            if (
                !sessionCacheItem ||
                timestampMs - sessionCacheItem.session.lastActivityTimestamp > config.sessionInactivityMs
            ) {
                // If the session didn't exist, or has expired, create a new session
                sessionId = new UUID7(timestampMs)
                sessionCacheItem = sessionCache[sessionRedisKey] = {
                    session: { sessionId: sessionId, lastActivityTimestamp: timestampMs },
                    isDirty: true,
                }
            } else {
                // otherwise, update the timestamp
                sessionId = sessionCacheItem.session.sessionId
                sessionCacheItem.session.lastActivityTimestamp = timestampMs
                sessionCacheItem.isDirty = true
            }

            // we now have enough information to update the events
            const newProperties: Properties = {
                ...eventWithProcessing.event.properties,
                $distinct_id: undefined,
                $device_id: baseHashToDeviceId(baseHash),
                $session_id: sessionId.toString(),
            }
            const newEvent = { ...eventWithProcessing.event, properties: newProperties }

            if (eventWithProcessing.event.event === '$identify') {
                // identify event, so the anon_distinct_id must be the sentinel and needs to be replaced
                newProperties['$anon_distinct_id'] = distinctId
            } else if (eventWithProcessing.event.distinct_id === COOKIELESS_SENTINEL_VALUE) {
                // event before identify has been called, distinct id is the sentinel and needs to be replaced
                newEvent.distinct_id = distinctId
            }

            eventWithProcessing.event = stripPIIProperties(newEvent)
        }

        // write identifies to redis
        const dirtyIdentifies = Object.entries(identifiesCache)
            .filter(([, value]) => value.isDirty)
            .map(([key, value]): [string, string[]] => {
                return [key, Array.from(value.identifyEventIds)]
            })
        if (dirtyIdentifies.length > 0) {
            await this.redisHelpers.redisSAddMulti(
                dirtyIdentifies,
                'CookielessManagerBatch.identifiesCacheWrite',
                this.config.identifiesTtlSeconds
            )
        }

        // write the session state to redis
        const dirtySessions = Object.entries(sessionCache)
            .filter(([, value]) => value.isDirty)
            .map(([key, value]): [string, Buffer] => {
                return [key, sessionStateToBuffer(value.session)]
            })
        if (dirtySessions.length > 0) {
            await this.redisHelpers.redisSetBufferMulti(
                dirtySessions,
                'CookielessManagerBatch.sessionCacheWrite',
                this.config.sessionTtlSeconds
            )
        }

        // Update results with successfully processed events
        for (const { event, team, message, headers, originalIndex } of eventsWithStatus) {
            results[originalIndex] = ok({ event, team, message, headers })
        }

        return results
    }

    dropAllCookielessEvents(
        events: IncomingEventWithTeam[],
        dropCause: string
    ): PipelineResult<IncomingEventWithTeam>[] {
        return events.map((incomingEvent) => {
            if (incomingEvent.event.properties?.[COOKIELESS_MODE_FLAG_PROPERTY]) {
                eventDroppedCounter
                    .labels({
                        event_type: 'analytics',
                        drop_cause: dropCause,
                    })
                    .inc()
                return drop(dropCause)
            } else {
                return ok(incomingEvent)
            }
        })
    }
}

type EventWithStatus = {
    message: Message
    event: PipelineEvent
    team: Team
    headers: EventHeaders
    originalIndex: number
    // Store temporary processing state. Nest the passes to make type-checking easier
    firstPass?: {
        timestampMs: number
        eventTimeZone: string | undefined
        ip: string
        host: string
        userAgent: string
        hashExtra: string | undefined
        baseHash: Buffer
        secondPass?: {
            identifiesRedisKey: string
            thirdPass?: {
                distinctId: string
                sessionRedisKey: string
            }
        }
    }
}

interface IdentifiesCacheState {
    identifyEventIds: Set<string>
    isDirty: boolean
}

interface SessionCacheState {
    session: SessionState
    isDirty: boolean
}

function getProperties(
    event: PluginEvent | PipelineEvent,
    timestamp: string
): {
    userAgent: string | undefined
    ip: string | undefined
    host: string | undefined
    timezone: string | undefined
    timestampMs: number
    hashExtra: string | undefined
} {
    const userAgent = event.properties?.['$raw_user_agent']
    const ip = event.properties?.['$ip']
    const host = event.properties?.['$host']
    const timezone = event.properties?.['$timezone']
    const hashExtra = event.properties?.[COOKIELESS_EXTRA_HASH_CONTENTS_PROPERTY]
    const timestampMs = DateTime.fromISO(timestamp).toMillis()

    return { userAgent, ip, host, timezone, timestampMs, hashExtra }
}

export function isCalendarDateValid(yyyymmdd: string): boolean {
    // make sure that the date is not in the future, i.e. at least one timezone could plausibly be in this calendar day,
    // and not too far in the past (with some buffer for ingestion lag)
    const utcDate = new Date(`${yyyymmdd}T00:00:00Z`)

    // Current time in UTC
    const nowUTC = new Date(Date.now())

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

export function hashToDistinctId(hash: Buffer): string {
    // add a prefix so that we can recognise one of these in the wild
    return 'cookieless_' + hash.toString('base64').replace(/=+$/, '')
}

export function baseHashToDeviceId(baseHash: Buffer): string {
    // add a prefix so that we can recognise one of these in the wild
    return 'cookielessd_' + baseHash.toString('base64').replace(/=+$/, '')
}

export function getRedisIdentifiesKey(hash: Buffer, teamId: number): string {
    // assuming 6 digits for team id, this is 6 + 2 + 6 + 24 = 38 characters
    // cklsi = cookieless identifies
    return `cklsi:${teamId}:${hash.toString('base64').replace(/=+$/, '')}`
}

export function getRedisSessionsKey(hash: Buffer, teamId: number): string {
    // assuming 6 digits for team id, this is 6 + 2 + 6 + 24 = 38 characters
    // cklss = cookieless sessions
    return `cklss:${teamId}:${hash.toString('base64').replace(/=+$/, '')}`
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
    hash: Buffer
): UUID7 {
    // A sessionId is a UUIDv7, which has a timestamp part and a random part. We need to find a deterministic way to
    // generate this ID whilst meeting the requirements of posthog session IDs
    // see https://posthog.com/docs/data/sessions#custom-session-ids

    // For the timestamp part, use the start of the day, in this user's timezone
    const timestampOfStartOfDay = toStartOfDayInTimezoneSafe(timestamp, eventTimezone, teamTimeZone).getTime()

    // For the random part, use the first 10 bytes of the hash (74 bits are actually used), as a way of ensuring
    // determinism with no state
    const fakeRandomBytes = hash.subarray(0, 10)

    return new UUID7(timestampOfStartOfDay, fakeRandomBytes)
}

export function stripPIIProperties(event: PipelineEvent) {
    if (event.properties) {
        // we use these properties in the hash, but they should not be written to disk if explicit consent was not given
        delete event.properties['$ip']
        delete event.properties['$raw_user_agent']
        delete event.properties[COOKIELESS_EXTRA_HASH_CONTENTS_PROPERTY]
    }
    if (event.properties?.$set) {
        delete event.properties.$set['$raw_user_agent']
    }
    if (event.properties?.$set_once) {
        delete event.properties.$set_once['$initial_raw_user_agent']
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

/**
 * Extract the root domain from a host string
 *
 * This function handles various formats including:
 * - URLs with protocols (e.g., https://example.com)
 * - Hosts with ports (e.g., example.com:8000)
 * - Subdomains (e.g., sub.example.com)
 * - IPv4 and IPv6 addresses
 *
 * It returns the root domain (eTLD+1) for valid domains, or the original host for
 * special cases like IP addresses, localhost, etc.
 * The port is preserved if present in the original host.
 */
export function extractRootDomain(input: string): string {
    // If the host is empty, return it as is
    if (!input) {
        return input
    }

    if (isIPv6(input)) {
        // Usually we would expect URLS, which would need to wrap literal ipv6 addresses in square brackets per RFC 2732.
        // Handle raw ipv6 addresses just in case, and return them normalized with square brackets.
        try {
            const ip = parse(input)
            return `[${ip.toString()}]`
        } catch {
            return input
        }
    }

    if (!input.includes('://')) {
        // add a fake protocol to make URL parsing work
        input = `http://${input}`
    }

    // Extract hostname and port
    let hostname: string
    let port: string | undefined
    try {
        const url = new URL(input)
        hostname = url.hostname
        port = url.port
    } catch {
        // If the URL parsing fails, return the original host
        return input
    }

    // Get the root domain using tldts
    let domain = getDomain(hostname) ?? hostname

    // if domain is localhost, map to 127.0.0.1 to make local dev easier
    if (domain === 'localhost') {
        domain = '127.0.0.1'
    }

    // Add the port back if it exists
    return port ? `${domain}:${port}` : domain
}
