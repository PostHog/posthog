import { Client as CassandraClient } from 'cassandra-driver'
import { createHash } from 'crypto'

import { truncateBehavioralCounters } from '../../../tests/helpers/cassandra'
import { createAction, getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { KAFKA_CDP_PERSON_PERFORMED_EVENT } from '../../config/kafka-topics'
import { Hub, RawClickHouseEvent, Team } from '../../types'
import { BehavioralCounterRepository } from '../../utils/db/cassandra/behavioural-counter.repository'
import { closeHub, createHub } from '../../utils/db/hub'
import { createIncomingEvent } from '../_tests/fixtures'
import { convertClickhouseRawEventToFilterGlobals } from '../utils/hog-function-filtering'
import { BehavioralEvent, CdpBehaviouralEventsConsumer } from './cdp-behavioural-events.consumer'

class TestableCdpBehaviouralEventsConsumer extends CdpBehaviouralEventsConsumer {
    // Expose protected properties through public getters for testing
    public get testCassandra() {
        return this.cassandra
    }
    public get testBehavioralCounterRepository() {
        return this.behavioralCounterRepository
    }
    public get testKafkaProducer() {
        return this.kafkaProducer
    }
    public get testPersonPerformedEventsQueue() {
        return this.personPerformedEventsQueue
    }

    public async testPublishPersonPerformedEvents() {
        return this.publishPersonPerformedEvents()
    }

    public async testProcessEvent(event: BehavioralEvent, counterUpdates: any[]) {
        return this.processEvent(event, counterUpdates)
    }
}

jest.setTimeout(20_000)

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
    describe('with Cassandra enabled', () => {
        let processor: TestableCdpBehaviouralEventsConsumer
        let hub: Hub
        let team: Team
        let cassandra: CassandraClient
        let repository: BehavioralCounterRepository

        beforeAll(async () => {
            await resetTestDatabase()
            hub = await createHub({ WRITE_BEHAVIOURAL_COUNTERS_TO_CASSANDRA: true })
            team = await getFirstTeam(hub)
            processor = new TestableCdpBehaviouralEventsConsumer(hub)
            const cassandraClient = processor.testCassandra

            if (!cassandraClient) {
                throw new Error('Cassandra client should be initialized when flag is enabled')
            }

            cassandra = cassandraClient
            await cassandra.connect()
            repository = processor.testBehavioralCounterRepository!
        })

        beforeEach(async () => {
            await resetTestDatabase()
            await truncateBehavioralCounters(cassandra)
            // Clear action manager cache to ensure test isolation
            try {
                ;(hub.actionManagerCDP as any).lazyLoader?.clear()
            } catch (e) {
                // Ignore cache clearing errors
            }
        })

        afterAll(async () => {
            await cassandra.shutdown()
            await closeHub(hub)
        })

        afterEach(() => {
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
                const result = await processor.testProcessEvent(behavioralEvent, counterUpdates)
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
                const result = await processor.testProcessEvent(behavioralEvent, counterUpdates)
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
                const result = await processor.testProcessEvent(behavioralEvent, counterUpdates)
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
        })
    })

    describe('with Cassandra disabled', () => {
        let processor: TestableCdpBehaviouralEventsConsumer
        let hub: Hub
        let team: Team

        beforeAll(async () => {
            await resetTestDatabase()
            hub = await createHub({ WRITE_BEHAVIOURAL_COUNTERS_TO_CASSANDRA: false })
            team = await getFirstTeam(hub)
            processor = new TestableCdpBehaviouralEventsConsumer(hub)

            // Processor should not have initialized Cassandra
            expect(processor.testCassandra).toBeNull()
            expect(processor.testBehavioralCounterRepository).toBeNull()
        })

        beforeEach(async () => {
            await resetTestDatabase()
            // Clear action manager cache to ensure test isolation
            try {
                ;(hub.actionManagerCDP as any).lazyLoader?.clear()
            } catch (e) {
                // Ignore cache clearing errors
            }
        })

        afterAll(async () => {
            await closeHub(hub)
        })

        afterEach(() => {
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
            expect(processor.testBehavioralCounterRepository).toBeNull()
        })
    })

    describe('CDP Person Performed Events', () => {
        let processor: TestableCdpBehaviouralEventsConsumer
        let hub: Hub
        let team: Team

        beforeAll(async () => {
            await resetTestDatabase()
            hub = await createHub()
            team = await getFirstTeam(hub)
            processor = new TestableCdpBehaviouralEventsConsumer(hub)
            await processor.start()
        })

        beforeEach(async () => {
            await resetTestDatabase()
            // Clear action manager cache to ensure test isolation
            try {
                ;(hub.actionManagerCDP as any).lazyLoader?.clear()
            } catch (e) {
                // Ignore cache clearing errors
            }
            // Clear the queue to ensure test isolation
            processor.testPersonPerformedEventsQueue.length = 0
        })

        afterAll(async () => {
            await processor.stop()
            await closeHub(hub)
        })

        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('should queue person performed events during message parsing', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const eventName = '$pageview'

            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            team_id: team.id,
                            event: eventName,
                            person_id: personId,
                            properties: '{"$browser": "Chrome"}',
                        } as RawClickHouseEvent)
                    ),
                } as any,
            ]

            // Parse messages which should queue person performed events
            await processor._parseKafkaBatch(messages)

            // Check that the event was queued
            const queue = processor.testPersonPerformedEventsQueue
            expect(queue).toHaveLength(1)
            expect(queue[0]).toEqual({
                teamId: team.id,
                personId,
                eventName,
            })
        })

        it('should publish person performed events to Kafka', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const eventName = '$pageview'

            // Spy on the real Kafka producer
            const queueMessagesSpy = jest
                .spyOn(processor.testKafkaProducer!, 'queueMessages')
                .mockResolvedValue(undefined)

            // Add an event to the queue manually
            processor.testPersonPerformedEventsQueue.push({
                teamId: team.id,
                personId,
                eventName,
            })

            // Publish the events
            await processor.testPublishPersonPerformedEvents()

            // Verify Kafka producer was called with correct message
            expect(queueMessagesSpy).toHaveBeenCalledTimes(1)
            expect(queueMessagesSpy).toHaveBeenCalledWith({
                topic: KAFKA_CDP_PERSON_PERFORMED_EVENT,
                messages: [
                    {
                        topic: KAFKA_CDP_PERSON_PERFORMED_EVENT,
                        value: JSON.stringify({
                            teamId: team.id,
                            personId,
                            eventName,
                        }),
                        key: team.id.toString(),
                    },
                ],
            })

            // Verify queue was cleared
            expect(processor.testPersonPerformedEventsQueue).toHaveLength(0)
        })

        it('should handle multiple events with different team IDs and correct partitioning', async () => {
            const events = [
                { teamId: 1, personId: 'person1', eventName: 'event1' },
                { teamId: 2, personId: 'person2', eventName: 'event2' },
                { teamId: 1, personId: 'person3', eventName: 'event3' },
            ]

            // Spy on the real Kafka producer
            const queueMessagesSpy = jest
                .spyOn(processor.testKafkaProducer!, 'queueMessages')
                .mockResolvedValue(undefined)

            // Add events to the queue
            events.forEach((event) => processor.testPersonPerformedEventsQueue.push(event))

            // Publish the events
            await processor.testPublishPersonPerformedEvents()

            // Verify messages have correct keys for partitioning
            const call = queueMessagesSpy.mock.calls[0][0] as { messages: { key: string }[] }
            expect(call.messages).toHaveLength(3)
            expect(call.messages[0].key).toBe('1')
            expect(call.messages[1].key).toBe('2')
            expect(call.messages[2].key).toBe('1')
        })

        it('should handle publishing errors gracefully', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const eventName = '$pageview'

            // Spy on the real Kafka producer to throw an error
            jest.spyOn(processor.testKafkaProducer!, 'queueMessages').mockRejectedValue(new Error('Kafka error'))

            // Spy on logger to verify error is logged
            const loggerSpy = jest.spyOn(require('../../utils/logger').logger, 'error')

            // Add an event to the queue
            processor.testPersonPerformedEventsQueue.push({
                teamId: team.id,
                personId,
                eventName,
            })

            // Publish should not throw
            await expect(processor.testPublishPersonPerformedEvents()).resolves.not.toThrow()

            // Verify error was logged
            expect(loggerSpy).toHaveBeenCalledWith(
                'Error publishing person performed events',
                expect.objectContaining({
                    error: expect.any(Error),
                    queueLength: 1,
                })
            )

            // Queue should NOT be cleared on error - messages should be retried
            expect(processor.testPersonPerformedEventsQueue).toHaveLength(1)
        })
    })
})
