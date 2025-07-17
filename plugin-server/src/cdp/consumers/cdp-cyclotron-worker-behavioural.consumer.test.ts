import { PostgresUse } from '~/utils/db/postgres'

import { getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { createIncomingEvent } from '../_tests/fixtures'
import { convertToHogFunctionInvocationGlobals } from '../utils'
import { CdpCyclotronWorkerBehaviouralConsumer } from './cdp-cyclotron-worker-behavioural.consumer'

jest.setTimeout(5000)

describe('CdpCyclotronWorkerBehaviouralConsumer', () => {
    let processor: CdpCyclotronWorkerBehaviouralConsumer
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        processor = new CdpCyclotronWorkerBehaviouralConsumer(hub)
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.restoreAllMocks()
    })

    describe('action matching with actual database', () => {
        it('should match action when event matches bytecode filter', async () => {
            // Insert an action directly into the database
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

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                'INSERT INTO posthog_action (id, name, description, team_id, deleted, bytecode, post_to_slack, slack_message_format, is_calculating, last_calculated_at, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW(), NOW())',
                [1, 'Test action', 'Test action', team.id, false, JSON.stringify(bytecode), false, '', false],
                'insert-test-action'
            )

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
            // Insert an action directly into the database
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

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                'INSERT INTO posthog_action (id, name, description, team_id, deleted, bytecode, post_to_slack, slack_message_format, is_calculating, last_calculated_at, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW(), NOW())',
                [2, 'Test action', 'Test action', team.id, false, JSON.stringify(bytecode), false, '', false],
                'insert-test-action'
            )

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
