import fs from 'fs'
import { Message } from 'node-rdkafka'
import path from 'path'

import type { PluginEvent } from '@posthog/plugin-scaffold'

import { createTestEventHeaders } from '~/tests/helpers/event-headers'
import { createOrganization, createTeam, getTeam } from '~/tests/helpers/sql'

import { cookielessRedisErrorCounter } from '../../common/metrics'
import { CookielessServerHashMode, Hub, PipelineEvent, Team } from '../../types'
import { RedisOperationError } from '../../utils/db/error'
import { closeHub, createHub } from '../../utils/db/hub'
import { PostgresUse } from '../../utils/db/postgres'
import { parseJSON } from '../../utils/json-parse'
import { UUID7 } from '../../utils/utils'
import { PipelineResultType, isOkResult } from '../pipelines/results'
import {
    COOKIELESS_MODE_FLAG_PROPERTY,
    COOKIELESS_SENTINEL_VALUE,
    CookielessManager,
    bufferToSessionState,
    extractRootDomain,
    getRedisIdentifiesKey,
    hashToDistinctId,
    isCalendarDateValid,
    sessionStateToBuffer,
    toYYYYMMDDInTimezoneSafe,
} from './cookieless-manager'

function deepFreeze<T extends object>(t: T): T {
    function deepFreezeInner(obj: any) {
        if (obj === null || typeof obj !== 'object') {
            return
        }
        if (Object.isFrozen(obj)) {
            return
        }
        Object.freeze(obj)
        Object.keys(obj).forEach((key) => {
            if (key in obj) {
                deepFreezeInner(obj[key])
            }
        })
        return obj
    }
    deepFreezeInner(t)
    return t
}

describe('CookielessManager', () => {
    describe('sessionStateToBuffer', () => {
        it('should return a binary representation of the session state which can be converted back to the original', () => {
            const date = new Date('2024-12-17T10:50Z')
            const uuidRand = Buffer.from('0123456789ABCDEF0123', 'hex')
            const sessionId = new UUID7(date.getTime(), uuidRand)

            // check that the bytes are as expected
            const sessionStateBuf = sessionStateToBuffer({ sessionId, lastActivityTimestamp: date.getTime() })
            expect(sessionStateBuf.toString('hex')).toMatchInlineSnapshot(
                `"0193d43d2fc07123856789abcdef0123c02f3dd493010000"`
            )

            // make sure its reversible
            const sessionState = bufferToSessionState(sessionStateBuf)
            expect(sessionState.lastActivityTimestamp).toEqual(date.getTime())
            expect(sessionState.sessionId).toEqual(sessionId)
        })
    })

    describe('toYYYYMMDDInTimezoneSafe', () => {
        it('should return a string in the format YYYY-MM-DD giving the date in the given time zone', () => {
            const date = new Date('2024-12-31T10:00:00Z').getTime()
            const result = toYYYYMMDDInTimezoneSafe(date, 'Europe/London', 'UTC')
            expect(result).toEqual('2024-12-31')
        })
        it('should handle single digit months and days', () => {
            const date = new Date('2025-01-01T10:00:00Z').getTime()
            const result = toYYYYMMDDInTimezoneSafe(date, 'Europe/London', 'UTC')
            expect(result).toEqual('2025-01-01')
        })
        it('should handle the user sending a nonsense timezone', () => {
            const date = new Date('2025-01-01T10:00:00Z').getTime()
            const result = toYYYYMMDDInTimezoneSafe(date, 'Not/A/Timezone', 'UTC')
            expect(result).toEqual('2025-01-01')
        })
        it('should handle a positive time zone', () => {
            const timezone = 'Asia/Tehran' // +3:30
            const date = new Date('2025-01-01T20:30:01Z').getTime()
            const result = toYYYYMMDDInTimezoneSafe(date, timezone, timezone)
            expect(result).toEqual('2025-01-02')
        })
        it('should handle a large positive time zone', () => {
            const timezone = 'Pacific/Tongatapu' // + 14
            const date = new Date('2025-01-01T12:00:00Z').getTime()
            const result = toYYYYMMDDInTimezoneSafe(date, timezone, timezone)
            expect(result).toEqual('2025-01-02')
        })
        it('should handle a negative time zone', () => {
            const timezone = 'America/Sao_Paulo' // -3
            const date = new Date('2025-01-01T02:59:00Z').getTime()
            const result = toYYYYMMDDInTimezoneSafe(date, timezone, timezone)
            expect(result).toEqual('2024-12-31')
        })
        it('should handle a large negative time zone', () => {
            const timezone = 'Pacific/Midway' // -11
            const date = new Date('2025-01-01T10:59:00Z').getTime()
            const result = toYYYYMMDDInTimezoneSafe(date, timezone, timezone)
            expect(result).toEqual('2024-12-31')
        })
        it('should prefer the event time zone over the team time zone', () => {
            const date = new Date('2025-01-01T12:00:00Z').getTime()
            const result = toYYYYMMDDInTimezoneSafe(date, 'Pacific/Tongatapu', 'UTC')
            expect(result).toEqual('2025-01-02')
        })
    })

    describe('isCalendarDateValid', () => {
        const fixedTime = new Date('2025-11-13T12:00:00Z')

        beforeEach(() => {
            jest.useFakeTimers({ now: fixedTime })
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('should accept today', () => {
            // Fixed time: 2025-11-13 12:00 UTC
            expect(isCalendarDateValid('2025-11-13')).toBe(true)
        })

        it('should accept yesterday', () => {
            // Salt window for 2025-11-12: Nov 11 12:00 to Nov 15 14:00
            // NOW (Nov 13 12:00) is within window
            expect(isCalendarDateValid('2025-11-12')).toBe(true)
        })

        it('should accept 3 days ago (within 72h + timezone buffer)', () => {
            // Salt window for 2025-11-10: Nov 9 12:00 to Nov 13 14:00
            // NOW (Nov 13 12:00) is within window
            expect(isCalendarDateValid('2025-11-10')).toBe(true)
        })

        it('should reject 4 days ago (salt window expired)', () => {
            // Salt window for 2025-11-09: Nov 8 12:00 to Nov 12 14:00
            // NOW (Nov 13 12:00) is after window ended
            expect(isCalendarDateValid('2025-11-09')).toBe(false)
        })

        it('should reject 5 days ago (salt window expired)', () => {
            // Salt window for 2025-11-08: Nov 7 12:00 to Nov 11 14:00
            // NOW (Nov 13 12:00) is well after window ended
            expect(isCalendarDateValid('2025-11-08')).toBe(false)
        })

        it('should reject tomorrow-ish dates', () => {
            // Salt window for 2025-11-08: Nov 7 12:00 to Nov 11 14:00
            // NOW (Nov 13 12:00) is well after window ended
            expect(isCalendarDateValid('2025-11-15')).toBe(false)
        })

        it('should reject invalid date format', () => {
            expect(isCalendarDateValid('not-a-date')).toBe(false)
            expect(isCalendarDateValid('2025/01/01')).toBe(false)
            expect(isCalendarDateValid('2025-13-01')).toBe(false)
        })
    })

    describe('pipeline step', () => {
        let hub: Hub
        let organizationId: string
        let teamId: number
        let team: Team
        const now = new Date('2025-01-10T11:00:00Z')
        const aBitLater = new Date('2025-01-10T11:10:00Z')
        const muchLater = new Date('2025-01-10T19:00:00Z')
        const differentDay = new Date('2025-01-11T11:00:00Z')
        const userAgent = 'Test User Agent'
        const identifiedDistinctId = 'identified@example.com'
        let event: PluginEvent
        let eventABitLater: PluginEvent
        let eventMuchLater: PluginEvent
        let eventDifferentDay: PluginEvent
        let eventOtherUser: PluginEvent
        let identifyEvent: PluginEvent
        let identifyEventABitLater: PluginEvent
        let postIdentifyEvent: PluginEvent
        let aliasEvent: PluginEvent
        let mergeDangerouslyEvent: PluginEvent
        let nonCookielessEvent: PluginEvent
        let eventWithExtra: PluginEvent
        const message = {
            a: 'message',
        } as unknown as Message

        beforeAll(async () => {
            hub = await createHub({})
            organizationId = await createOrganization(hub.postgres)

            jest.useFakeTimers({
                now,
                advanceTimers: true,
            })
        })
        afterAll(async () => {
            await closeHub(hub)

            jest.clearAllTimers()
        })

        const setModeForTeam = async (mode: CookielessServerHashMode) => {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_team SET cookieless_server_hash_mode = $1 WHERE id = $2`,
                [mode, teamId],
                'set team to cookieless'
            )
            team = (await getTeam(hub, teamId))!
        }

        const clearRedis = async () => {
            const client = await hub.redisPool.acquire()
            await client.flushall()
            await hub.redisPool.release(client)
        }

        beforeEach(async () => {
            await clearRedis()
            hub.cookielessManager.deleteAllLocalSalts()
            teamId = await createTeam(hub.postgres, organizationId)
            team = (await getTeam(hub, teamId))!
            event = deepFreeze({
                event: 'test event',
                distinct_id: COOKIELESS_SENTINEL_VALUE,
                properties: {
                    [COOKIELESS_MODE_FLAG_PROPERTY]: true,
                    $host: 'https://example.com',
                    $raw_user_agent: userAgent,
                    $ip: '1.2.3.4',
                },
                site_url: 'https://example.com',
                team_id: teamId,
                now: now.toISOString(),
                uuid: new UUID7(now.getTime()).toString(),
                ip: null,
            })
            eventABitLater = deepFreeze({
                ...event,
                now: aBitLater.toISOString(),
                uuid: new UUID7(aBitLater.getTime()).toString(),
            })
            eventMuchLater = deepFreeze({
                ...event,
                now: muchLater.toISOString(),
                uuid: new UUID7(muchLater.getTime()).toString(),
            })
            eventOtherUser = deepFreeze({
                ...event,
                properties: {
                    ...event.properties,
                    $ip: '5.6.7.8',
                },
                uuid: new UUID7(now.getTime()).toString(),
            })
            eventDifferentDay = deepFreeze({
                ...event,
                now: differentDay.toISOString(),
                uuid: new UUID7(differentDay.getTime()).toString(),
            })
            identifyEvent = deepFreeze({
                event: '$identify',
                distinct_id: identifiedDistinctId,
                properties: {
                    [COOKIELESS_MODE_FLAG_PROPERTY]: true,
                    $anon_distinct_id: COOKIELESS_SENTINEL_VALUE,
                    $host: 'https://example.com',
                    $raw_user_agent: userAgent,
                    $ip: '1.2.3.4',
                },
                site_url: 'https://example.com',
                team_id: teamId,
                now: now.toISOString(),
                uuid: new UUID7(now.getTime()).toString(),
                ip: null,
            })
            identifyEventABitLater = deepFreeze({
                ...identifyEvent,
                now: aBitLater.toISOString(),
                uuid: new UUID7(aBitLater.getTime()).toString(),
            })
            postIdentifyEvent = deepFreeze({
                event: 'test event',
                distinct_id: identifiedDistinctId,
                properties: {
                    [COOKIELESS_MODE_FLAG_PROPERTY]: true,
                    $host: 'https://example.com',
                    $raw_user_agent: userAgent,
                    $ip: '1.2.3.4',
                },
                site_url: 'https://example.com',
                team_id: teamId,
                now: now.toISOString(),
                uuid: new UUID7(now.getTime()).toString(),
                ip: null,
            })
            aliasEvent = deepFreeze({
                ...event,
                event: '$create_alias',
                uuid: new UUID7(now.getTime()).toString(),
            })
            mergeDangerouslyEvent = deepFreeze({
                ...event,
                event: '$merge_dangerously',
                uuid: new UUID7(now.getTime()).toString(),
            })
            nonCookielessEvent = deepFreeze({
                ...event,
                properties: {
                    $host: 'https://example.com',
                    $raw_user_agent: userAgent,
                },
                uuid: new UUID7(now.getTime()).toString(),
            })
            eventWithExtra = deepFreeze({
                ...event,
                properties: {
                    ...event.properties,
                    $cookieless_extra: 'extra',
                },
                uuid: new UUID7(now.getTime()).toString(),
            })
        })

        async function processEvent(
            event: PipelineEvent,
            headers: {
                token?: string
                distinct_id?: string
                timestamp?: string
                force_disable_person_processing: boolean
                historical_migration: boolean
            } = createTestEventHeaders()
        ): Promise<PipelineEvent | undefined> {
            const response = await hub.cookielessManager.doBatch([{ event, team, message, headers }])
            expect(response.length).toBe(1)
            const result = response[0]
            return isOkResult(result) ? result.value.event : undefined
        }

        async function processEventWithHeaders(
            event: PipelineEvent,
            headers: {
                token?: string
                distinct_id?: string
                timestamp?: string
                force_disable_person_processing: boolean
                historical_migration: boolean
            }
        ): Promise<{
            event: PipelineEvent | undefined
            headers: {
                token?: string
                distinct_id?: string
                timestamp?: string
                force_disable_person_processing: boolean
                historical_migration: boolean
            }
        }> {
            const response = await hub.cookielessManager.doBatch([{ event, team, message, headers }])
            expect(response.length).toBe(1)
            const result = response[0]
            return {
                event: isOkResult(result) ? result.value.event : undefined,
                headers: isOkResult(result)
                    ? result.value.headers || createTestEventHeaders()
                    : createTestEventHeaders(),
            }
        }

        // tests that are shared between both modes
        describe.each([
            ['stateless', CookielessServerHashMode.Stateless],
            ['stateful', CookielessServerHashMode.Stateful],
        ])('common (%s)', (_, mode) => {
            beforeEach(async () => {
                await setModeForTeam(mode)
            })
            it('should give an event a distinct id and session id ', async () => {
                const actual = await processEvent(event)

                if (!actual?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual.distinct_id).not.toEqual(COOKIELESS_SENTINEL_VALUE)
                expect(actual.distinct_id.startsWith('cookieless_')).toBe(true)
                expect(actual.properties.$session_id).toBeTruthy()
            })
            it('should give the same session id and distinct id to events with the same hash properties and within the same day and session timeout period', async () => {
                const actual1 = await processEvent(event)
                const actual2 = await processEvent(eventABitLater)

                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.distinct_id).toEqual(actual1.distinct_id)
                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).toEqual(actual1.properties.$session_id)
            })
            it('should give different distinct id and session id to a user with a different IP', async () => {
                const actual1 = await processEvent(event)
                const actual2 = await processEvent(eventOtherUser)
                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual1.distinct_id).not.toEqual(actual2.distinct_id)
                expect(actual1.properties.$session_id).not.toEqual(actual2.properties.$session_id)
            })
            it('should give different distinct id and session id to events on different days', async () => {
                const actual1 = await processEvent(event)
                jest.setSystemTime(differentDay) // advance time to the next day
                const actual2 = await processEvent(eventDifferentDay)
                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual1.distinct_id).not.toEqual(actual2.distinct_id)
                expect(actual1.properties.$session_id).not.toEqual(actual2.properties.$session_id)
            })
            it('should strip the PII used in the hash', async () => {
                const actual = await processEvent(eventWithExtra)

                if (!actual?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual.ip).toBeNull()
                expect(actual.properties.$raw_user_user).toBeUndefined()
                expect(actual.properties.$ip).toBeUndefined()
                expect(actual.properties.$cookieless_extra).toBeUndefined()
            })
            it('should drop alias and merge events', async () => {
                const actual1 = await processEvent(aliasEvent)
                const actual2 = await processEvent(mergeDangerouslyEvent)
                expect(actual1).toBeUndefined()
                expect(actual2).toBeUndefined()
            })
            it('should pass through non-cookieless events', async () => {
                const actual1 = await processEvent(nonCookielessEvent)
                expect(actual1).toBe(nonCookielessEvent)
            })
            it('should work even if the local salt map is torn down between events (as it can use redis)', async () => {
                const actual1 = await processEvent(event)
                hub.cookielessManager.deleteAllLocalSalts()
                const actual2 = await processEvent(eventABitLater)

                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.distinct_id).toEqual(actual1.distinct_id)
                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).toEqual(actual1.properties.$session_id)
            })
            it('should count as a different user if the extra value is different', async () => {
                const actual1 = await processEvent(event)
                const actual2 = await processEvent(eventWithExtra)

                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual1.distinct_id).not.toEqual(actual2.distinct_id)
                expect(actual1.properties.$session_id).not.toEqual(actual2.properties.$session_id)
            })

            it('should not return dropped events but should not throw', async () => {
                // Test with alias event which should be dropped
                const actual = await processEvent(aliasEvent)

                // Dropped events return undefined
                expect(actual).toBeUndefined()
            })
        })

        describe('stateless', () => {
            beforeEach(async () => {
                await setModeForTeam(CookielessServerHashMode.Stateless)
            })

            it('should provide the same session ID for events within the same day, later than the session timeout', async () => {
                // this is actually a limitation of this mode, but we have the same test (with a different outcome) for stateful mode

                const actual1 = await processEvent(event)
                const actual2 = await processEvent(eventMuchLater)

                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.distinct_id).toEqual(actual1.distinct_id)
                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).toEqual(actual1.properties.$session_id)
            })

            it('should drop identify events', async () => {
                // this is also a limitation of this mode
                const actual1 = await processEvent(identifyEvent)
                expect(actual1).toBeUndefined()
            })

            it('should work even if redis is cleared (as it can use the local cache)', async () => {
                const actual1 = await processEvent(event)
                await clearRedis()
                const actual2 = await processEvent(eventABitLater)

                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.distinct_id).toEqual(actual1.distinct_id)
                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).toEqual(actual1.properties.$session_id)
            })

            it('should preserve headers through cookieless processing', async () => {
                const testHeaders = {
                    token: 'test-token',
                    distinct_id: 'test-distinct-id',
                    timestamp: '1234567890',
                    force_disable_person_processing: false,
                    historical_migration: false,
                }

                const result = await processEventWithHeaders(event, testHeaders)

                expect(result.headers).toEqual(testHeaders)
                expect(result.event).toBeDefined()
            })

            it('should preserve headers for non-cookieless events', async () => {
                const testHeaders = {
                    token: 'test-token',
                    distinct_id: 'test-distinct-id',
                    timestamp: '1234567890',
                    force_disable_person_processing: false,
                    historical_migration: false,
                }

                const result = await processEventWithHeaders(nonCookielessEvent, testHeaders)

                expect(result.headers).toEqual(testHeaders)
                expect(result.event).toBe(nonCookielessEvent)
            })

            it('should not return dropped events but should not throw', async () => {
                const testHeaders = {
                    token: 'test-token',
                    distinct_id: 'test-distinct-id',
                    timestamp: '1234567890',
                    force_disable_person_processing: false,
                    historical_migration: false,
                }

                // Test with alias event which should be dropped
                const result = await processEventWithHeaders(aliasEvent, testHeaders)

                // Dropped events are not returned in the response array
                expect(result.event).toBeUndefined()
                expect(result.headers).toEqual(createTestEventHeaders())
            })
        })

        describe('stateful', () => {
            beforeEach(async () => {
                await setModeForTeam(CookielessServerHashMode.Stateful)
            })
            it('should provide a different session ID after session timeout', async () => {
                const actual1 = await processEvent(event)
                const actual2 = await processEvent(eventMuchLater)

                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.distinct_id).toEqual(actual1.distinct_id)
                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).not.toEqual(actual1.properties.$session_id)
            })
            it('should handle a user identifying', async () => {
                const actual1 = await processEvent(event)
                const actual2 = await processEvent(identifyEvent)
                const actual3 = await processEvent(postIdentifyEvent)

                if (!actual1?.properties || !actual2?.properties || !actual3?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.properties.$anon_distinct_id).toEqual(actual1.distinct_id)

                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).toEqual(actual1.properties.$session_id)
                expect(actual3.properties.$session_id).toEqual(actual1.properties.$session_id)
            })
            it('should handle identify events in an idempotent way', async () => {
                const actual1 = await processEvent(event)
                const actual2 = await processEvent(identifyEvent)
                const actual3 = await processEvent(identifyEvent)

                if (!actual1?.properties || !actual2?.properties || !actual3?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.properties.$anon_distinct_id).toEqual(actual1.distinct_id)
                expect(actual3.properties.$anon_distinct_id).toEqual(actual1.distinct_id)

                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).toEqual(actual1.properties.$session_id)
                expect(actual3.properties.$session_id).toEqual(actual1.properties.$session_id)
            })
            it('should treat anon events after an identify as if there was a logout, and as a different person', async () => {
                const actual1 = await processEvent(event)
                const actual2 = await processEvent(identifyEvent)
                const actual3 = await processEvent(eventABitLater)
                const actual4 = await processEvent(identifyEventABitLater)

                if (!actual1?.properties || !actual2?.properties || !actual3?.properties || !actual4?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.properties.$anon_distinct_id).toEqual(actual1.distinct_id)
                expect(actual3.distinct_id).not.toEqual(actual1.distinct_id)
                expect(actual4.properties.$anon_distinct_id).toEqual(actual3.distinct_id)
                expect(actual4.properties.$anon_distinct_id).not.toEqual(actual2.properties.$anon_distinct_id)

                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).toEqual(actual1.properties.$session_id)
                expect(actual3.properties.$session_id).not.toEqual(actual1.properties.$session_id)
                expect(actual3.properties.$session_id).toBeDefined()
                expect(actual4.properties.$session_id).toEqual(actual3.properties.$session_id)
            })
            it('should increment the redis error counter if redis errors', async () => {
                const operation = 'scard'
                const error = new RedisOperationError('redis error', new Error(), operation, { key: 'key' })
                jest.spyOn(hub.cookielessManager.redisHelpers, 'redisSMembersMulti').mockImplementationOnce(() => {
                    throw error
                })
                const spy = jest.spyOn(cookielessRedisErrorCounter, 'labels')
                const result = await processEvent(event)
                expect(result).toEqual(undefined)
                expect(spy.mock.calls[0]).toEqual([{ operation }])
            })

            it('should DLQ cookieless events when Redis error occurs', async () => {
                const operation = 'scard'
                const redisError = new RedisOperationError('redis error', new Error(), operation, { key: 'key' })
                jest.spyOn(hub.cookielessManager.redisHelpers, 'redisSMembersMulti').mockImplementationOnce(() => {
                    throw redisError
                })

                const response = await hub.cookielessManager.doBatch([
                    { event, team, message, headers: createTestEventHeaders() },
                    { event: nonCookielessEvent, team, message, headers: createTestEventHeaders() },
                ])
                expect(response.length).toBe(2)

                // Cookieless event should be DLQ'd
                const cookielessResult = response[0]
                expect(cookielessResult.type).toBe(PipelineResultType.DLQ)
                if (cookielessResult.type === PipelineResultType.DLQ) {
                    expect(cookielessResult.reason).toBe('cookieless_fail_close')
                    expect(cookielessResult.error).toBe(redisError)
                }

                // Non-cookieless event should pass through
                const nonCookielessResult = response[1]
                expect(nonCookielessResult.type).toBe(PipelineResultType.OK)
                if (nonCookielessResult.type === PipelineResultType.OK) {
                    expect(nonCookielessResult.value.event).toBe(nonCookielessEvent)
                }
            })

            it('should DLQ cookieless events when unexpected error occurs', async () => {
                const unexpectedError = new Error('Something went wrong')
                jest.spyOn(hub.cookielessManager.redisHelpers, 'redisSMembersMulti').mockImplementationOnce(() => {
                    throw unexpectedError
                })

                const response = await hub.cookielessManager.doBatch([
                    { event, team, message, headers: createTestEventHeaders() },
                    { event: nonCookielessEvent, team, message, headers: createTestEventHeaders() },
                ])
                expect(response.length).toBe(2)

                // Cookieless event should be DLQ'd
                const cookielessResult = response[0]
                expect(cookielessResult.type).toBe(PipelineResultType.DLQ)
                if (cookielessResult.type === PipelineResultType.DLQ) {
                    expect(cookielessResult.reason).toBe('cookieless_fail_close')
                    expect(cookielessResult.error).toBe(unexpectedError)
                }

                // Non-cookieless event should pass through
                const nonCookielessResult = response[1]
                expect(nonCookielessResult.type).toBe(PipelineResultType.OK)
                if (nonCookielessResult.type === PipelineResultType.OK) {
                    expect(nonCookielessResult.value.event).toBe(nonCookielessEvent)
                }
            })
        })
        describe('timestamp out of range', () => {
            beforeEach(async () => {
                await setModeForTeam(CookielessServerHashMode.Stateful)
            })

            it('should drop only the event with out-of-range timestamp, not other events in batch', async () => {
                // Create an event with a timestamp that's too old (more than 72h + timezone buffer in the past)
                const oldTimestamp = new Date('2025-01-05T11:00:00Z') // 5 days before "now" (2025-01-10)
                const eventWithOldTimestamp = deepFreeze({
                    ...event,
                    now: oldTimestamp.toISOString(),
                    uuid: new UUID7(oldTimestamp.getTime()).toString(),
                })

                const response = await hub.cookielessManager.doBatch([
                    {
                        event: eventWithOldTimestamp,
                        team,
                        message,
                        headers: createTestEventHeaders(),
                    },
                    { event, team, message, headers: createTestEventHeaders() },
                    { event: nonCookielessEvent, team, message, headers: createTestEventHeaders() },
                ])
                expect(response.length).toBe(3)

                // Event with old timestamp should be dropped
                const oldTimestampResult = response[0]
                expect(oldTimestampResult.type).toBe(PipelineResultType.DROP)
                if (oldTimestampResult.type === PipelineResultType.DROP) {
                    expect(oldTimestampResult.reason).toBe('cookieless_timestamp_out_of_range')
                }

                // Valid cookieless event should pass through
                const validCookielessResult = response[1]
                expect(validCookielessResult.type).toBe(PipelineResultType.OK)

                // Non-cookieless event should pass through
                const nonCookielessResult = response[2]
                expect(nonCookielessResult.type).toBe(PipelineResultType.OK)
                if (nonCookielessResult.type === PipelineResultType.OK) {
                    expect(nonCookielessResult.value.event).toBe(nonCookielessEvent)
                }
            })

            it('should drop events with timestamps too far in the future', async () => {
                // Create an event with a timestamp that's too far in the future
                const futureTimestamp = new Date('2025-01-12T11:00:00Z') // 2 days after "now" (2025-01-10)
                const eventWithFutureTimestamp = deepFreeze({
                    ...event,
                    now: futureTimestamp.toISOString(),
                    uuid: new UUID7(futureTimestamp.getTime()).toString(),
                })

                const response = await hub.cookielessManager.doBatch([
                    {
                        event: eventWithFutureTimestamp,
                        team,
                        message,
                        headers: createTestEventHeaders(),
                    },
                    { event, team, message, headers: createTestEventHeaders() },
                ])
                expect(response.length).toBe(2)

                // Event with future timestamp should be dropped
                const futureTimestampResult = response[0]
                expect(futureTimestampResult.type).toBe(PipelineResultType.DROP)
                if (futureTimestampResult.type === PipelineResultType.DROP) {
                    expect(futureTimestampResult.reason).toBe('cookieless_timestamp_out_of_range')
                }

                // Valid cookieless event should pass through
                const validCookielessResult = response[1]
                expect(validCookielessResult.type).toBe(PipelineResultType.OK)
            })

            it('should include ingestion warning for dropped events', async () => {
                const oldTimestamp = new Date('2025-01-05T11:00:00Z')
                const eventWithOldTimestamp = deepFreeze({
                    ...event,
                    now: oldTimestamp.toISOString(),
                    uuid: new UUID7(oldTimestamp.getTime()).toString(),
                })

                const response = await hub.cookielessManager.doBatch([
                    {
                        event: eventWithOldTimestamp,
                        team,
                        message,
                        headers: createTestEventHeaders(),
                    },
                ])
                expect(response.length).toBe(1)

                const result = response[0]
                expect(result.type).toBe(PipelineResultType.DROP)
                if (result.type === PipelineResultType.DROP) {
                    expect(result.warnings.length).toBe(1)
                    expect(result.warnings[0].type).toBe('cookieless_timestamp_out_of_range')
                    expect(result.warnings[0].details).toMatchObject({
                        eventUuid: eventWithOldTimestamp.uuid,
                        event: eventWithOldTimestamp.event,
                        distinctId: eventWithOldTimestamp.distinct_id,
                    })
                }
            })
        })
        describe('disabled', () => {
            beforeEach(async () => {
                await setModeForTeam(CookielessServerHashMode.Disabled)
            })
            it('should drop all events', async () => {
                const actual1 = await processEvent(event)
                expect(actual1).toBeUndefined()
            })
            it('should pass through non-cookieless events', async () => {
                const actual1 = await processEvent(nonCookielessEvent)
                expect(actual1).toBe(nonCookielessEvent)
            })
            it('should not return dropped cookieless events but should not throw', async () => {
                const testHeaders = {
                    token: 'test-token',
                    distinct_id: 'test-distinct-id',
                    timestamp: '1234567890',
                    force_disable_person_processing: false,
                    historical_migration: false,
                }

                const result = await processEventWithHeaders(event, testHeaders)

                // Dropped events are not returned in the response array
                expect(result.event).toBeUndefined()
                expect(result.headers).toEqual(createTestEventHeaders())
            })
            it('should preserve headers when passing through non-cookieless events', async () => {
                const testHeaders = {
                    token: 'test-token',
                    distinct_id: 'test-distinct-id',
                    timestamp: '1234567890',
                    force_disable_person_processing: false,
                    historical_migration: false,
                }

                const result = await processEventWithHeaders(nonCookielessEvent, testHeaders)

                expect(result.headers).toEqual(testHeaders)
                expect(result.event).toBe(nonCookielessEvent)
            })
        })

        describe('ingestion warnings', () => {
            beforeEach(async () => {
                await setModeForTeam(CookielessServerHashMode.Stateful)
            })

            it('should emit warning when timestamp is missing', async () => {
                const eventWithoutTimestamp = deepFreeze({
                    ...event,
                    now: undefined as any,
                    timestamp: undefined as any,
                    sent_at: undefined as any,
                })

                const response = await hub.cookielessManager.doBatch([
                    {
                        event: eventWithoutTimestamp,
                        team,
                        message,
                        headers: createTestEventHeaders(),
                    },
                ])
                expect(response.length).toBe(1)
                const result = response[0]

                expect(result.type).toBe(PipelineResultType.DROP)
                if (result.type === PipelineResultType.DROP) {
                    expect(result.reason).toBe('cookieless_missing_timestamp')
                }
                expect(result.warnings).toHaveLength(1)
                expect(result.warnings[0]).toMatchObject({
                    type: 'cookieless_missing_timestamp',
                    details: {
                        eventUuid: eventWithoutTimestamp.uuid,
                        event: eventWithoutTimestamp.event,
                        distinctId: eventWithoutTimestamp.distinct_id,
                    },
                })
            })

            it('should emit warning when user agent is missing', async () => {
                const eventWithoutUA = deepFreeze({
                    ...event,
                    properties: {
                        ...event.properties,
                        $raw_user_agent: undefined,
                    },
                })

                const response = await hub.cookielessManager.doBatch([
                    { event: eventWithoutUA, team, message, headers: createTestEventHeaders() },
                ])
                expect(response.length).toBe(1)
                const result = response[0]

                expect(result.type).toBe(PipelineResultType.DROP)
                if (result.type === PipelineResultType.DROP) {
                    expect(result.reason).toBe('cookieless_missing_ua')
                }
                expect(result.warnings).toHaveLength(1)
                expect(result.warnings[0]).toMatchObject({
                    type: 'cookieless_missing_user_agent',
                    details: {
                        eventUuid: eventWithoutUA.uuid,
                        event: eventWithoutUA.event,
                        distinctId: eventWithoutUA.distinct_id,
                        missingProperty: '$raw_user_agent',
                    },
                })
            })

            it('should emit warning when IP is missing', async () => {
                const eventWithoutIP = deepFreeze({
                    ...event,
                    properties: {
                        ...event.properties,
                        $ip: undefined,
                    },
                })

                const response = await hub.cookielessManager.doBatch([
                    { event: eventWithoutIP, team, message, headers: createTestEventHeaders() },
                ])
                expect(response.length).toBe(1)
                const result = response[0]

                expect(result.type).toBe(PipelineResultType.DROP)
                if (result.type === PipelineResultType.DROP) {
                    expect(result.reason).toBe('cookieless_missing_ip')
                }
                expect(result.warnings).toHaveLength(1)
                expect(result.warnings[0]).toMatchObject({
                    type: 'cookieless_missing_ip',
                    details: {
                        eventUuid: eventWithoutIP.uuid,
                        event: eventWithoutIP.event,
                        distinctId: eventWithoutIP.distinct_id,
                        missingProperty: '$ip',
                    },
                })
            })

            it('should emit warning when host is missing', async () => {
                const eventWithoutHost = deepFreeze({
                    ...event,
                    properties: {
                        ...event.properties,
                        $host: undefined,
                    },
                })

                const response = await hub.cookielessManager.doBatch([
                    { event: eventWithoutHost, team, message, headers: createTestEventHeaders() },
                ])
                expect(response.length).toBe(1)
                const result = response[0]

                expect(result.type).toBe(PipelineResultType.DROP)
                if (result.type === PipelineResultType.DROP) {
                    expect(result.reason).toBe('cookieless_missing_host')
                }
                expect(result.warnings).toHaveLength(1)
                expect(result.warnings[0]).toMatchObject({
                    type: 'cookieless_missing_host',
                    details: {
                        eventUuid: eventWithoutHost.uuid,
                        event: eventWithoutHost.event,
                        distinctId: eventWithoutHost.distinct_id,
                        missingProperty: '$host',
                    },
                })
            })
        })
    })

    describe('rust implementation compatibility', () => {
        // Make sure that this TS implementation of cookieless matches up with the Rust implementation
        // We do this with a shared test case file that is used by both the Rust and TS tests

        // Don't import, as importing from outside our package directory will change the shape of the build directory
        // instead, just find the file path and load it directly
        const TEST_CASES_PATH = path.resolve(__dirname, '../../../../rust/common/cookieless/src/test_cases.json')
        const TEST_CASES: Record<string, any[]> = parseJSON(fs.readFileSync(TEST_CASES_PATH, 'utf8'))

        describe('doHash', () => {
            it.each(TEST_CASES.test_cases)(
                'should hash the inputs',
                ({ salt, team_id, ip, expected, root_domain, user_agent, n, hash_extra }) => {
                    const saltBuf = Buffer.from(salt, 'base64')
                    const resultBuf = CookielessManager.doHash(
                        saltBuf,
                        team_id,
                        ip,
                        root_domain,
                        user_agent,
                        n,
                        hash_extra
                    )
                    const result = resultBuf.toString('base64')
                    expect(result).toEqual(expected)
                }
            )
        })

        describe('hashToDistinctId', () => {
            it.each(TEST_CASES.hash_to_distinct_id_tests)(
                'should correctly convert a hash to a distinct ID',
                ({ hash, expected_distinct_id }) => {
                    const hashBuf = Buffer.from(hash, 'base64')

                    const distinctId = hashToDistinctId(hashBuf)
                    expect(distinctId).toEqual(expected_distinct_id)
                }
            )
        })

        describe('getRedisIdentifiesKey', () => {
            it.each(TEST_CASES.redis_identifies_key_tests)(
                'should correctly convert a hash to a distinct ID',
                ({ hash, team_id, expected_identifies_key }) => {
                    const hashBuf = Buffer.from(hash, 'base64')

                    const distinctId = getRedisIdentifiesKey(hashBuf, team_id)
                    expect(distinctId).toEqual(expected_identifies_key)
                }
            )
        })

        describe('extractRootDomain', () => {
            it.each(TEST_CASES.extract_root_domain_tests)(
                'should correctly extract the root domain from $host',
                ({ host, expected_root_domain }) => {
                    const result = extractRootDomain(host)
                    expect(result).toEqual(expected_root_domain)
                }
            )
        })
    })
})
