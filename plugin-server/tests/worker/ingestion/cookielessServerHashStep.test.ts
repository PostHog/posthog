import type { PluginEvent } from '@posthog/plugin-scaffold'

import { CookielessServerHashMode, Hub } from '../../../src/types'
import { closeHub, createHub } from '../../../src/utils/db/hub'
import { PostgresUse } from '../../../src/utils/db/postgres'
import { deepFreeze, UUID7 } from '../../../src/utils/utils'
import {
    bufferToSessionState,
    COOKIELESS_MODE_FLAG_PROPERTY,
    COOKIELESS_SENTINEL_VALUE,
    cookielessServerHashStep,
    sessionStateToBuffer,
    toYYYYMMDDInTimezoneSafe,
} from '../../../src/worker/ingestion/event-pipeline/cookielessServerHashStep'
import { createOrganization, createTeam } from '../../helpers/sql'

describe('cookielessServerHashStep', () => {
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
    })

    describe('pipeline step', () => {
        let hub: Hub
        let organizationId: string
        let teamId: number
        const now = new Date('2025-01-10T11:00:00')
        const aBitLater = new Date('2025-01-10T11:10:00')
        const muchLater = new Date('2025-01-10T19:00:00')
        const differentDay = new Date('2025-01-11T11:00:00')
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

        beforeAll(async () => {
            hub = await createHub({})

            organizationId = await createOrganization(hub.db.postgres)

            jest.useFakeTimers({
                now,
                advanceTimers: true,
            })
        })
        afterAll(() => {
            closeHub(hub)

            jest.clearAllTimers()
        })

        const setModeForTeam = async (mode: CookielessServerHashMode, teamId: number) => {
            await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_team SET cookieless_server_hash_mode = $1 WHERE id = $2`,
                [mode, teamId],
                'set team to cookieless'
            )
        }

        beforeEach(async () => {
            teamId = await createTeam(hub.db.postgres, organizationId)
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
            })
            mergeDangerouslyEvent = deepFreeze({
                ...event,
                event: '$merge_dangerously',
            })
            nonCookielessEvent = deepFreeze({
                ...event,
                properties: {
                    $host: 'https://example.com',
                    $raw_user_agent: userAgent,
                },
            })
        })

        // tests that are shared between both modes
        describe.each([
            ['stateless', CookielessServerHashMode.Stateless],
            ['stateful', CookielessServerHashMode.Stateful],
        ])('common (%s)', (_, mode) => {
            beforeEach(async () => {
                await setModeForTeam(mode, teamId)
            })
            it('should give an event a distinct id and session id ', async () => {
                const [actual] = await cookielessServerHashStep(hub, event)

                if (!actual?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual.distinct_id).not.toEqual(COOKIELESS_SENTINEL_VALUE)
                expect(actual.distinct_id.startsWith('cookieless_')).toBe(true)
                expect(actual.properties.$session_id).toBeDefined()
            })
            it('should give the same session id and distinct id to events with the same hash properties and within the same day and session timeout period', async () => {
                const [actual1] = await cookielessServerHashStep(hub, event)
                const [actual2] = await cookielessServerHashStep(hub, eventABitLater)

                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.distinct_id).toEqual(actual1.distinct_id)
                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).toEqual(actual1.properties.$session_id)
            })
            it('should give different distinct id and session id to a user with a different IP', async () => {
                const [actual1] = await cookielessServerHashStep(hub, event)
                const [actual2] = await cookielessServerHashStep(hub, eventOtherUser)
                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual1.distinct_id).not.toEqual(actual2.distinct_id)
                expect(actual1.properties.$session_id).not.toEqual(actual2.properties.$session_id)
            })
            it('should give different distinct id and session id to events on different days', async () => {
                const [actual1] = await cookielessServerHashStep(hub, event)
                jest.setSystemTime(differentDay) // advance time to the next day
                const [actual2] = await cookielessServerHashStep(hub, eventDifferentDay)
                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual1.distinct_id).not.toEqual(actual2.distinct_id)
                expect(actual1.properties.$session_id).not.toEqual(actual2.properties.$session_id)
            })
            it('should strip the PII used in the hash', async () => {
                const [actual] = await cookielessServerHashStep(hub, event)

                if (!actual?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual.ip).toBeNull()
                expect(actual.properties.$raw_user_user).toBeUndefined()
                expect(actual.properties.$ip).toBeUndefined()
                expect(actual.properties.$cookieless_extra).toBeUndefined()
            })
            it('should drop alias and merge events', async () => {
                const [actual1] = await cookielessServerHashStep(hub, aliasEvent)
                const [actual2] = await cookielessServerHashStep(hub, mergeDangerouslyEvent)
                expect(actual1).toBeUndefined()
                expect(actual2).toBeUndefined()
            })
            it('should pass through non-cookieless events', async () => {
                const [actual1] = await cookielessServerHashStep(hub, nonCookielessEvent)
                expect(actual1).toBe(nonCookielessEvent)
            })
        })

        describe('stateless', () => {
            beforeEach(async () => {
                await setModeForTeam(CookielessServerHashMode.Stateless, teamId)
            })

            it('should provide the same session ID for events within the same day, later than the session timeout', async () => {
                // this is actually a limitation of this mode, but we have the same test (with a different outcome) for stateful mode

                const [actual1] = await cookielessServerHashStep(hub, event)
                const [actual2] = await cookielessServerHashStep(hub, eventMuchLater)

                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.distinct_id).toEqual(actual1.distinct_id)
                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).toEqual(actual1.properties.$session_id)
            })

            it('should drop identify events', async () => {
                // this is also a limitation of this mode
                const [actual1] = await cookielessServerHashStep(hub, identifyEvent)
                expect(actual1).toBeUndefined()
            })
        })

        describe('stateful', () => {
            beforeEach(async () => {
                await setModeForTeam(CookielessServerHashMode.Stateful, teamId)
            })
            it('should provide a different session ID after session timeout', async () => {
                const [actual1] = await cookielessServerHashStep(hub, event)
                const [actual2] = await cookielessServerHashStep(hub, eventMuchLater)

                if (!actual1?.properties || !actual2?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.distinct_id).toEqual(actual1.distinct_id)
                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).not.toEqual(actual1.properties.$session_id)
            })
            it('should handle a user identifying', async () => {
                const [actual1] = await cookielessServerHashStep(hub, event)
                const [actual2] = await cookielessServerHashStep(hub, identifyEvent)
                const [actual3] = await cookielessServerHashStep(hub, postIdentifyEvent)

                if (!actual1?.properties || !actual2?.properties || !actual3?.properties) {
                    throw new Error('no event or properties')
                }
                expect(actual2.properties.$anon_distinct_id).toEqual(actual1.distinct_id)

                expect(actual1.properties.$session_id).toBeDefined()
                expect(actual2.properties.$session_id).toEqual(actual1.properties.$session_id)
                expect(actual3.properties.$session_id).toEqual(actual1.properties.$session_id)
            })
            it('should handle identify events in an idempotent way', async () => {
                const [actual1] = await cookielessServerHashStep(hub, event)
                const [actual2] = await cookielessServerHashStep(hub, identifyEvent)
                const [actual3] = await cookielessServerHashStep(hub, identifyEvent)

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
                const [actual1] = await cookielessServerHashStep(hub, event)
                const [actual2] = await cookielessServerHashStep(hub, identifyEvent)
                const [actual3] = await cookielessServerHashStep(hub, eventABitLater)
                const [actual4] = await cookielessServerHashStep(hub, identifyEventABitLater)

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
        })
        describe('disabled', () => {
            beforeEach(async () => {
                await setModeForTeam(CookielessServerHashMode.Disabled, teamId)
            })
            it('should drop all events', async () => {
                const [actual1] = await cookielessServerHashStep(hub, event)
                expect(actual1).toBeUndefined()
            })
            it('should pass through non-cookieless events', async () => {
                const [actual1] = await cookielessServerHashStep(hub, nonCookielessEvent)
                expect(actual1).toBe(nonCookielessEvent)
            })
        })
    })
})
