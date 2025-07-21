import { createAction, getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, RawClickHouseEvent, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { createIncomingEvent } from '../_tests/fixtures'
import { convertClickhouseRawEventToFilterGlobals } from '../utils/hog-function-filtering'
import { BehavioralEvent, CdpBehaviouralEventsConsumer } from './cdp-behavioural-events.consumer'

jest.setTimeout(5000)

describe('CdpBehaviouralEventsConsumer', () => {
    let processor: CdpBehaviouralEventsConsumer
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        processor = new CdpBehaviouralEventsConsumer(hub)
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.restoreAllMocks()
    })

    describe('action matching with actual database', () => {
        it('should match action when event matches bytecode filter', async () => {
            // Create an action with bytecode
            const bytecode = [
                '_H',
                1,
                32,
                'Chrome',
                32,
                '$browser',
                32,
                'properties',
                1,
                2,
                11,
                32,
                '$pageview',
                32,
                'event',
                1,
                1,
                11,
                3,
                2,
                4,
                1,
            ]

            await createAction(hub.postgres, team.id, 'Test action', bytecode)

            // Create a matching event
            const matchingEvent = createIncomingEvent(team.id, {
                event: '$pageview',
                properties: JSON.stringify({ $browser: 'Chrome' }),
            } as RawClickHouseEvent)

            const filterGlobals = convertClickhouseRawEventToFilterGlobals(matchingEvent)
            const behavioralEvent: BehavioralEvent = {
                teamId: team.id,
                filterGlobals,
            }

            // Verify the action was loaded
            const actions = await hub.actionManagerCDP.getActionsForTeam(team.id)
            expect(actions).toHaveLength(1)
            expect(actions[0].name).toBe('Test action')

            // Test processEvent directly and verify it returns 1 for matching event
            const result = await (processor as any).processEvent(behavioralEvent)
            expect(result).toBe(1)
        })

        it('should not match action when event does not match bytecode filter', async () => {
            // Create an action with bytecode
            const bytecode = [
                '_H',
                1,
                32,
                'Chrome',
                32,
                '$browser',
                32,
                'properties',
                1,
                2,
                11,
                32,
                '$pageview',
                32,
                'event',
                1,
                1,
                11,
                3,
                2,
                4,
                1,
            ]

            await createAction(hub.postgres, team.id, 'Test action', bytecode)

            // Create a non-matching event
            const nonMatchingEvent = createIncomingEvent(team.id, {
                event: '$pageview',
                properties: JSON.stringify({ $browser: 'Firefox' }), // Different browser
            } as RawClickHouseEvent)

            const filterGlobals = convertClickhouseRawEventToFilterGlobals(nonMatchingEvent)
            const behavioralEvent: BehavioralEvent = {
                teamId: team.id,
                filterGlobals,
            }

            // Verify the action was loaded
            const actions = await hub.actionManagerCDP.getActionsForTeam(team.id)
            expect(actions).toHaveLength(1)
            expect(actions[0].name).toBe('Test action')

            // Test processEvent directly and verify it returns 0 for non-matching event
            const result = await (processor as any).processEvent(behavioralEvent)
            expect(result).toBe(0)
        })

        it('should return count of matched actions when multiple actions match', async () => {
            // Create multiple actions with different bytecode
            const pageViewBytecode = ['_H', 1, 32, '$pageview', 32, 'event', 1, 1, 11]

            const filterBytecode = [
                '_H',
                1,
                32,
                '$pageview',
                32,
                'event',
                1,
                1,
                11,
                32,
                '%Chrome%',
                32,
                '$browser',
                32,
                'properties',
                1,
                2,
                2,
                'toString',
                1,
                18,
                3,
                2,
                32,
                '$pageview',
                32,
                'event',
                1,
                1,
                11,
                31,
                32,
                '$ip',
                32,
                'properties',
                1,
                2,
                12,
                3,
                2,
                4,
                2,
            ]

            await createAction(hub.postgres, team.id, 'Pageview action', pageViewBytecode)
            await createAction(hub.postgres, team.id, 'Filter action', filterBytecode)

            // Create an event that matches both actions
            const matchingEvent = createIncomingEvent(team.id, {
                event: '$pageview',
                properties: JSON.stringify({ $browser: 'Chrome', $ip: '127.0.0.1' }),
            } as RawClickHouseEvent)

            const filterGlobals = convertClickhouseRawEventToFilterGlobals(matchingEvent)
            const behavioralEvent: BehavioralEvent = {
                teamId: team.id,
                filterGlobals,
            }

            // Test processEvent directly and verify it returns 2 for both matching actions
            const result = await (processor as any).processEvent(behavioralEvent)
            expect(result).toBe(2)
        })
    })
})
