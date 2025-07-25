import { Client as CassandraClient } from 'cassandra-driver'
import { createHash } from 'crypto'

import { truncateBehavioralCounters } from '../../../tests/helpers/cassandra'
import { createAction, getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, RawClickHouseEvent, Team } from '../../types'
import { BehavioralCounterRepository } from '../../utils/db/cassandra/behavioural-counter.repository'
import { closeHub, createHub } from '../../utils/db/hub'
import { createIncomingEvent } from '../_tests/fixtures'
import { convertClickhouseRawEventToFilterGlobals } from '../utils/hog-function-filtering'
import { BehavioralEvent, CdpBehaviouralEventsConsumer, counterEventsDropped } from './cdp-behavioural-events.consumer'

class TestCdpBehaviouralEventsConsumer extends CdpBehaviouralEventsConsumer {
    public getCassandraClient(): CassandraClient | null {
        return this.cassandra
    }

    public getBehavioralCounterRepository(): BehavioralCounterRepository | null {
        return this.behavioralCounterRepository
    }
}

jest.setTimeout(5000)

const TEST_FILTERS = {
    // Simple pageview event filter: event == '$pageview'
    pageview: ['_H', 1, 32, '$pageview', 32, 'event', 1, 1, 11],

    // Chrome browser AND pageview event filter: properties.$browser == 'Chrome' AND event == '$pageview'
    chromePageview: [
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
    ],

    // Complex filter: pageview event AND (Chrome browser contains match OR has IP property)
    complexChromeWithIp: [
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
    ],
}

describe('CdpBehaviouralEventsConsumer', () => {
    // Helper function to setup test environment with Cassandra enabled
    async function setupWithCassandraEnabled() {
        await resetTestDatabase()
        const hub = await createHub({ WRITE_BEHAVIOURAL_COUNTERS_TO_CASSANDRA: true })
        const team = await getFirstTeam(hub)
        const processor = new TestCdpBehaviouralEventsConsumer(hub)
        const cassandra = processor.getCassandraClient()

        if (!cassandra) {
            throw new Error('Cassandra client should be initialized when flag is enabled')
        }

        await cassandra.connect()
        const repository = processor.getBehavioralCounterRepository()!
        await truncateBehavioralCounters(cassandra)

        return { hub, team, processor, cassandra, repository }
    }

    // Helper function to setup test environment with Cassandra disabled
    async function setupWithCassandraDisabled() {
        await resetTestDatabase()
        const hub = await createHub({ WRITE_BEHAVIOURAL_COUNTERS_TO_CASSANDRA: false })
        const team = await getFirstTeam(hub)
        const processor = new TestCdpBehaviouralEventsConsumer(hub)

        // Processor should not have initialized Cassandra
        expect(processor.getCassandraClient()).toBeNull()
        expect(processor.getBehavioralCounterRepository()).toBeNull()

        return { hub, team, processor }
    }

    describe('with Cassandra enabled', () => {
        let processor: TestCdpBehaviouralEventsConsumer
        let hub: Hub
        let team: Team
        let cassandra: CassandraClient
        let repository: BehavioralCounterRepository

        beforeEach(async () => {
            const setup = await setupWithCassandraEnabled()
            hub = setup.hub
            team = setup.team
            processor = setup.processor
            cassandra = setup.cassandra
            repository = setup.repository
        })

        afterEach(async () => {
            await cassandra.shutdown()
            await closeHub(hub)
            jest.restoreAllMocks()
        })

        describe('action matching with actual database', () => {
            it('should match action when event matches bytecode filter', async () => {
                // Create an action with Chrome + pageview filter
                await createAction(hub.postgres, team.id, 'Test action', TEST_FILTERS.chromePageview)

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
                // Create an action with Chrome + pageview filter
                await createAction(hub.postgres, team.id, 'Test action', TEST_FILTERS.chromePageview)

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
                // Create multiple actions with different filters
                await createAction(hub.postgres, team.id, 'Pageview action', TEST_FILTERS.pageview)
                await createAction(hub.postgres, team.id, 'Complex filter action', TEST_FILTERS.complexChromeWithIp)

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

                await createAction(hub.postgres, team.id, 'Test action', TEST_FILTERS.chromePageview)

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

                const counter = await repository.getCounter({
                    teamId: team.id,
                    filterHash,
                    personId,
                    date: today,
                })

                expect(counter).not.toBeNull()
                expect(counter!.count).toBe(1)
            })

            it('should increment existing counter', async () => {
                // Arrange
                const personId = '550e8400-e29b-41d4-a716-446655440000'

                await createAction(hub.postgres, team.id, 'Test action', TEST_FILTERS.chromePageview)

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

                const counter = await repository.getCounter({
                    teamId: team.id,
                    filterHash,
                    personId,
                    date: today,
                })

                expect(counter).not.toBeNull()
                expect(counter!.count).toBe(2)
            })

            it('should not write counter when event does not match', async () => {
                // Arrange
                const personId = '550e8400-e29b-41d4-a716-446655440000'

                await createAction(hub.postgres, team.id, 'Test action', TEST_FILTERS.chromePageview)

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

                const counter = await repository.getCounter({
                    teamId: team.id,
                    filterHash,
                    personId,
                    date: today,
                })

                expect(counter).toBeNull()
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
                const counters = await repository.getCountersForTeam(team.id)

                expect(counters).toHaveLength(0)
            })
        })
    })

    describe('with Cassandra disabled', () => {
        let processor: TestCdpBehaviouralEventsConsumer
        let hub: Hub
        let team: Team

        beforeEach(async () => {
            const setup = await setupWithCassandraDisabled()
            hub = setup.hub
            team = setup.team
            processor = setup.processor
        })

        afterEach(async () => {
            await closeHub(hub)
            jest.restoreAllMocks()
        })

        it('should not write to Cassandra when WRITE_BEHAVIOURAL_COUNTERS_TO_CASSANDRA is false', async () => {
            // Arrange
            const personId = '550e8400-e29b-41d4-a716-446655440000'

            await createAction(hub.postgres, team.id, 'Test action', TEST_FILTERS.chromePageview)

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

            // Spy on the writeBehavioralCounters method to ensure it's never called when Cassandra is disabled
            const writeSpy = jest.spyOn(processor as any, 'writeBehavioralCounters')

            // Act
            await processor.processBatch([behavioralEvent])

            // Assert - writeBehavioralCounters should never be called when Cassandra is disabled
            expect(writeSpy).toHaveBeenCalledTimes(0)

            // Double-check repository is still null
            expect(processor.getBehavioralCounterRepository()).toBeNull()
        })
    })
})
