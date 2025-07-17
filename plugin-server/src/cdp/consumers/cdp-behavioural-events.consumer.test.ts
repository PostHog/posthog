import { createAction, getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { createIncomingEvent } from '../_tests/fixtures'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { CdpBehaviouralEventsConsumer } from './cdp-behavioural-events.consumer'

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
            })

            const globals = convertToHogFunctionInvocationGlobals(matchingEvent, team, hub.SITE_URL)

            // Verify the action was loaded
            const actions = await hub.actionManagerCDP.getActionsForTeam(team.id)
            expect(actions).toHaveLength(1)
            expect(actions[0].name).toBe('Test action')

            // Test processEvent directly and verify it returns true for matching event
            const result = await (processor as any).processEvent(globals)
            expect(result).toBe(true)
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
            })

            const globals = convertToHogFunctionInvocationGlobals(nonMatchingEvent, team, hub.SITE_URL)

            // Verify the action was loaded
            const actions = await hub.actionManagerCDP.getActionsForTeam(team.id)
            expect(actions).toHaveLength(1)
            expect(actions[0].name).toBe('Test action')

            // Test processEvent directly and verify it returns false for non-matching event
            const result = await (processor as any).processEvent(globals)
            expect(result).toBe(false)
        })
    })
})
