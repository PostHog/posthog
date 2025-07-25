import { Client as CassandraClient, types as CassandraTypes } from 'cassandra-driver'
import { createHash } from 'crypto'

import { createAction, getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, RawClickHouseEvent, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { createIncomingEvent } from '../_tests/fixtures'
import { convertClickhouseRawEventToFilterGlobals } from '../utils/hog-function-filtering'
import { BehavioralEvent, CdpBehaviouralEventsConsumer, counterEventsDropped } from './cdp-behavioural-events.consumer'

jest.setTimeout(5000)

describe('CdpBehaviouralEventsConsumer', () => {
    let processor: CdpBehaviouralEventsConsumer
    let hub: Hub
    let team: Team
    let cassandra: CassandraClient

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        cassandra = hub.cassandra
        processor = new CdpBehaviouralEventsConsumer(hub)

        // Clean up test data
        await cassandra.execute('TRUNCATE behavioral_event_counters')
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
                personId: '550e8400-e29b-41d4-a716-446655440000',
            }

            // Verify the action was loaded
            const actions = await hub.actionManagerCDP.getActionsForTeam(team.id)
            expect(actions).toHaveLength(1)
            expect(actions[0].name).toBe('Test action')

            // Test processEvent directly and verify it returns 1 for matching event
            const counterUpdates: any[] = []
            const result = await (processor as any).processEvent(behavioralEvent, counterUpdates)
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
                personId: '550e8400-e29b-41d4-a716-446655440000',
            }

            // Verify the action was loaded
            const actions = await hub.actionManagerCDP.getActionsForTeam(team.id)
            expect(actions).toHaveLength(1)
            expect(actions[0].name).toBe('Test action')

            // Test processEvent directly and verify it returns 0 for non-matching event
            const counterUpdates: any[] = []
            const result = await (processor as any).processEvent(behavioralEvent, counterUpdates)
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
                personId: '550e8400-e29b-41d4-a716-446655440000',
            }

            // Test processEvent directly and verify it returns 2 for both matching actions
            const counterUpdates: any[] = []
            const result = await (processor as any).processEvent(behavioralEvent, counterUpdates)
            expect(result).toBe(2)
        })
    })

    describe('Cassandra behavioral counter writes', () => {
        it('should write counter to Cassandra when action matches', async () => {
            // Arrange
            const personId = '550e8400-e29b-41d4-a716-446655440000'
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

            // Create a matching event with person ID
            const matchingEvent = createIncomingEvent(team.id, {
                event: '$pageview',
                properties: JSON.stringify({ $browser: 'Chrome' }),
                person_id: personId,
            } as RawClickHouseEvent)

            const filterGlobals = convertClickhouseRawEventToFilterGlobals(matchingEvent)
            const behavioralEvent: BehavioralEvent = {
                teamId: team.id,
                filterGlobals,
                personId,
            }

            // Act
            await processor.processBatch([behavioralEvent])

            // Assert - check that the counter was written to Cassandra
            const actions = await hub.actionManagerCDP.getActionsForTeam(team.id)
            const action = actions[0]
            const filterHash = createHash('sha256')
                .update(JSON.stringify(action.bytecode))
                .digest('hex')
                .substring(0, 16)
            const today = new Date().toISOString().split('T')[0]

            const cassandraResult = await cassandra.execute(
                'SELECT count FROM behavioral_event_counters WHERE team_id = ? AND filter_hash = ? AND person_id = ? AND date = ?',
                [team.id, filterHash, CassandraTypes.Uuid.fromString(personId), today],
                { prepare: true }
            )

            expect(cassandraResult.rows).toHaveLength(1)
            expect(cassandraResult.rows[0].count.toNumber()).toBe(1)
        })

        it('should increment existing counter', async () => {
            // Arrange
            const personId = '550e8400-e29b-41d4-a716-446655440000'
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

            const matchingEvent = createIncomingEvent(team.id, {
                event: '$pageview',
                properties: JSON.stringify({ $browser: 'Chrome' }),
                person_id: personId,
            } as RawClickHouseEvent)

            const filterGlobals = convertClickhouseRawEventToFilterGlobals(matchingEvent)
            const behavioralEvent: BehavioralEvent = {
                teamId: team.id,
                filterGlobals,
                personId,
            }

            // Act - process event twice
            await processor.processBatch([behavioralEvent])
            await processor.processBatch([behavioralEvent])

            // Assert - check that the counter was incremented
            const actions = await hub.actionManagerCDP.getActionsForTeam(team.id)
            const action = actions[0]
            const filterHash = createHash('sha256')
                .update(JSON.stringify(action.bytecode))
                .digest('hex')
                .substring(0, 16)
            const today = new Date().toISOString().split('T')[0]

            const cassandraResult = await cassandra.execute(
                'SELECT count FROM behavioral_event_counters WHERE team_id = ? AND filter_hash = ? AND person_id = ? AND date = ?',
                [team.id, filterHash, CassandraTypes.Uuid.fromString(personId), today],
                { prepare: true }
            )

            expect(cassandraResult.rows).toHaveLength(1)
            expect(cassandraResult.rows[0].count.toNumber()).toBe(2)
        })

        it('should not write counter when event does not match', async () => {
            // Arrange
            const personId = '550e8400-e29b-41d4-a716-446655440000'
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
                person_id: personId,
            } as RawClickHouseEvent)

            const filterGlobals = convertClickhouseRawEventToFilterGlobals(nonMatchingEvent)
            const behavioralEvent: BehavioralEvent = {
                teamId: team.id,
                filterGlobals,
                personId,
            }

            // Act
            await processor.processBatch([behavioralEvent])

            // Assert - check that no counter was written to Cassandra
            const actions = await hub.actionManagerCDP.getActionsForTeam(team.id)
            const action = actions[0]
            const filterHash = createHash('sha256')
                .update(JSON.stringify(action.bytecode))
                .digest('hex')
                .substring(0, 16)
            const today = new Date().toISOString().split('T')[0]

            const cassandraResult = await cassandra.execute(
                'SELECT count FROM behavioral_event_counters WHERE team_id = ? AND filter_hash = ? AND person_id = ? AND date = ?',
                [team.id, filterHash, CassandraTypes.Uuid.fromString(personId), today],
                { prepare: true }
            )

            expect(cassandraResult.rows).toHaveLength(0)
        })

        it('should drop events with missing person ID at parsing stage', async () => {
            // Create a raw event without person_id (simulating what comes from Kafka)
            const rawEventWithoutPersonId = {
                uuid: '12345',
                event: '$pageview',
                team_id: team.id,
                properties: JSON.stringify({ $browser: 'Chrome' }),
                // person_id is undefined
            }

            // Get initial metric value
            const initialDroppedCount = await counterEventsDropped.get()
            const initialMissingPersonIdCount =
                initialDroppedCount.values.find((v) => v.labels.reason === 'missing_person_id')?.value || 0

            const messages = [
                {
                    value: Buffer.from(JSON.stringify(rawEventWithoutPersonId)),
                },
            ] as any[]

            // Act - parse the batch (should drop the event)
            const parsedEvents = await (processor as any)._parseKafkaBatch(messages)

            // Assert - no events should be parsed due to missing person_id
            expect(parsedEvents).toHaveLength(0)

            // Assert - metric should be incremented
            const finalDroppedCount = await counterEventsDropped.get()
            const finalMissingPersonIdCount =
                finalDroppedCount.values.find((v) => v.labels.reason === 'missing_person_id')?.value || 0
            expect(finalMissingPersonIdCount).toBe(initialMissingPersonIdCount + 1)

            // Assert - no counter should be written to Cassandra since event was dropped
            const cassandraResult = await cassandra.execute(
                'SELECT * FROM behavioral_event_counters WHERE team_id = ?',
                [team.id],
                { prepare: true }
            )

            expect(cassandraResult.rows).toHaveLength(0)
        })
    })
})
