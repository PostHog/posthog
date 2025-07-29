import { Client as CassandraClient } from 'cassandra-driver'
import { createHash } from 'crypto'

import { truncateBehavioralCounters, truncatePersonEventOccurrences } from '../../../tests/helpers/cassandra'
import { createAction, getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub, RawClickHouseEvent, Team } from '../../types'
import { BehavioralCounterRepository } from '../../utils/db/cassandra/behavioural-counter.repository'
import { PersonEventOccurrenceRepository } from '../../utils/db/cassandra/person-event-occurrence.repository'
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

    public getPersonEventOccurrenceRepository(): PersonEventOccurrenceRepository | null {
        return this.personEventOccurrenceRepository
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
        const occurrenceRepository = processor.getPersonEventOccurrenceRepository()!
        await truncateBehavioralCounters(cassandra)
        await truncatePersonEventOccurrences(cassandra)

        return { hub, team, processor, cassandra, repository, occurrenceRepository }
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
        let occurrenceRepository: PersonEventOccurrenceRepository

        beforeEach(async () => {
            const setup = await setupWithCassandraEnabled()
            hub = setup.hub
            team = setup.team
            processor = setup.processor
            cassandra = setup.cassandra
            repository = setup.repository
            occurrenceRepository = setup.occurrenceRepository
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

        describe('Person event occurrence writes', () => {
            it('should write person event occurrence for every event processed', async () => {
                // Arrange
                const personId = '550e8400-e29b-41d4-a716-446655440000'
                const eventName = '$pageview'

                const event = createIncomingEvent(team.id, {
                    event: eventName,
                    properties: JSON.stringify({ $browser: 'Chrome' }),
                    person_id: personId,
                } as RawClickHouseEvent)

                const filterGlobals = convertClickhouseRawEventToFilterGlobals(event)
                const behavioralEvent: BehavioralEvent = {
                    teamId: team.id,
                    filterGlobals,
                    personId,
                }

                // Act
                await processor.processBatch([behavioralEvent])

                // Assert - check that occurrence was written regardless of action matching
                const hasOccurred = await occurrenceRepository.hasOccurred({
                    teamId: team.id,
                    personId,
                    eventName,
                })

                expect(hasOccurred).toBe(true)
            })

            it('should write occurrences for multiple different events', async () => {
                // Arrange
                const personId = '550e8400-e29b-41d4-a716-446655440000'
                const events = [
                    { eventName: '$pageview', browser: 'Chrome' },
                    { eventName: '$identify', browser: 'Firefox' },
                    { eventName: 'custom_event', browser: 'Safari' },
                ]

                const behavioralEvents = events.map(({ eventName, browser }) => {
                    const event = createIncomingEvent(team.id, {
                        event: eventName,
                        properties: JSON.stringify({ $browser: browser }),
                        person_id: personId,
                    } as RawClickHouseEvent)

                    const filterGlobals = convertClickhouseRawEventToFilterGlobals(event)
                    return {
                        teamId: team.id,
                        filterGlobals,
                        personId,
                    }
                })

                // Act
                await processor.processBatch(behavioralEvents)

                // Assert - check that all occurrences were written
                for (const { eventName } of events) {
                    const hasOccurred = await occurrenceRepository.hasOccurred({
                        teamId: team.id,
                        personId,
                        eventName,
                    })
                    expect(hasOccurred).toBe(true)
                }

                // Get all events for person to verify count
                const allEvents = await occurrenceRepository.getEventsForPerson(team.id, personId)
                expect(allEvents).toHaveLength(3)
                expect(allEvents.map((e) => e.event_name).sort()).toEqual(['$identify', '$pageview', 'custom_event'])
            })

            it('should handle duplicate events gracefully (idempotent writes)', async () => {
                // Arrange
                const personId = '550e8400-e29b-41d4-a716-446655440000'
                const eventName = '$pageview'

                const event = createIncomingEvent(team.id, {
                    event: eventName,
                    properties: JSON.stringify({ $browser: 'Chrome' }),
                    person_id: personId,
                } as RawClickHouseEvent)

                const filterGlobals = convertClickhouseRawEventToFilterGlobals(event)
                const behavioralEvent: BehavioralEvent = {
                    teamId: team.id,
                    filterGlobals,
                    personId,
                }

                // Act - process the same event multiple times
                await processor.processBatch([behavioralEvent])
                await processor.processBatch([behavioralEvent])
                await processor.processBatch([behavioralEvent])

                // Assert - occurrence should still exist (duplicate inserts are handled by compaction)
                const hasOccurred = await occurrenceRepository.hasOccurred({
                    teamId: team.id,
                    personId,
                    eventName,
                })

                expect(hasOccurred).toBe(true)

                // Get all events for person - should only show unique events
                const allEvents = await occurrenceRepository.getEventsForPerson(team.id, personId)
                expect(allEvents).toHaveLength(1)
                expect(allEvents[0].event_name).toBe(eventName)
            })

            it('should handle multiple persons performing the same event', async () => {
                // Arrange
                const person1Id = '550e8400-e29b-41d4-a716-446655440000'
                const person2Id = '550e8400-e29b-41d4-a716-446655440001'
                const eventName = '$pageview'

                const behavioralEvents = [person1Id, person2Id].map((personId) => {
                    const event = createIncomingEvent(team.id, {
                        event: eventName,
                        properties: JSON.stringify({ $browser: 'Chrome' }),
                        person_id: personId,
                    } as RawClickHouseEvent)

                    const filterGlobals = convertClickhouseRawEventToFilterGlobals(event)
                    return {
                        teamId: team.id,
                        filterGlobals,
                        personId,
                    }
                })

                // Act
                await processor.processBatch(behavioralEvents)

                // Assert - both persons should have the occurrence
                for (const personId of [person1Id, person2Id]) {
                    const hasOccurred = await occurrenceRepository.hasOccurred({
                        teamId: team.id,
                        personId,
                        eventName,
                    })
                    expect(hasOccurred).toBe(true)

                    const events = await occurrenceRepository.getEventsForPerson(team.id, personId)
                    expect(events).toHaveLength(1)
                    expect(events[0].event_name).toBe(eventName)
                }
            })

            it('should not write occurrences when events are dropped due to missing person_id', async () => {
                // Arrange - create raw event without person_id
                const rawEventWithoutPersonId = {
                    uuid: '12345',
                    event: '$pageview',
                    team_id: team.id,
                    properties: JSON.stringify({ $browser: 'Chrome' }),
                    // person_id is undefined
                }

                const messages = [
                    {
                        value: Buffer.from(JSON.stringify(rawEventWithoutPersonId)),
                    },
                ] as any[]

                // Act - parse and process the batch
                const parsedEvents = await (processor as any)._parseKafkaBatch(messages)
                await processor.processBatch(parsedEvents)

                // Assert - no events should be parsed, so no occurrences written
                expect(parsedEvents).toHaveLength(0)

                // Verify no occurrences were written by checking if any exist for this team
                // Since we don't have a "get all occurrences for team" method, we'll try a specific lookup
                // that should fail since no events were processed
                const hasAnyOccurrence = await occurrenceRepository.hasOccurred({
                    teamId: team.id,
                    personId: '550e8400-e29b-41d4-a716-446655440000', // any person id
                    eventName: '$pageview',
                })
                expect(hasAnyOccurrence).toBe(false)
            })

            it('should deduplicate occurrences within a single batch', async () => {
                // Arrange - create multiple identical events in the same batch
                const personId = '550e8400-e29b-41d4-a716-446655440000'
                const eventName = '$pageview'

                // Create 5 identical events (same person, same event)
                const identicalEvents = Array(5)
                    .fill(null)
                    .map(() => {
                        const event = createIncomingEvent(team.id, {
                            event: eventName,
                            properties: JSON.stringify({ $browser: 'Chrome' }),
                            person_id: personId,
                        } as RawClickHouseEvent)

                        const filterGlobals = convertClickhouseRawEventToFilterGlobals(event)
                        return {
                            teamId: team.id,
                            filterGlobals,
                            personId,
                        }
                    })

                // Act - process all identical events in a single batch
                await processor.processBatch(identicalEvents)

                // Assert - verify the occurrence exists (should be deduplicated to 1 record)
                const hasOccurred = await occurrenceRepository.hasOccurred({
                    teamId: team.id,
                    personId,
                    eventName,
                })
                expect(hasOccurred).toBe(true)

                // Verify only 1 event recorded for this person
                const allEvents = await occurrenceRepository.getEventsForPerson(team.id, personId)
                expect(allEvents).toHaveLength(1)
                expect(allEvents[0].event_name).toBe(eventName)
            })

            it('should deduplicate mixed events correctly within a batch', async () => {
                // Arrange - create a batch with some duplicates and some unique events
                const person1Id = '550e8400-e29b-41d4-a716-446655440000'
                const person2Id = '550e8400-e29b-41d4-a716-446655440001'

                const events = [
                    // 3x person1 + $pageview (should be deduplicated to 1)
                    { personId: person1Id, eventName: '$pageview' },
                    { personId: person1Id, eventName: '$pageview' },
                    { personId: person1Id, eventName: '$pageview' },
                    // 2x person1 + $identify (should be deduplicated to 1)
                    { personId: person1Id, eventName: '$identify' },
                    { personId: person1Id, eventName: '$identify' },
                    // 2x person2 + $pageview (should be deduplicated to 1)
                    { personId: person2Id, eventName: '$pageview' },
                    { personId: person2Id, eventName: '$pageview' },
                    // 1x person2 + custom_event (unique)
                    { personId: person2Id, eventName: 'custom_event' },
                ]

                const behavioralEvents = events.map(({ personId, eventName }) => {
                    const event = createIncomingEvent(team.id, {
                        event: eventName,
                        properties: JSON.stringify({ $browser: 'Chrome' }),
                        person_id: personId,
                    } as RawClickHouseEvent)

                    const filterGlobals = convertClickhouseRawEventToFilterGlobals(event)
                    return {
                        teamId: team.id,
                        filterGlobals,
                        personId,
                    }
                })

                // Act
                await processor.processBatch(behavioralEvents)

                // Assert - verify all unique combinations exist in the database
                const expectedOccurrences = [
                    { personId: person1Id, eventName: '$pageview' },
                    { personId: person1Id, eventName: '$identify' },
                    { personId: person2Id, eventName: '$pageview' },
                    { personId: person2Id, eventName: 'custom_event' },
                ]

                // Check each expected occurrence exists
                for (const { personId, eventName } of expectedOccurrences) {
                    const hasOccurred = await occurrenceRepository.hasOccurred({
                        teamId: team.id,
                        personId,
                        eventName,
                    })
                    expect(hasOccurred).toBe(true)
                }

                // Verify person1 has exactly 2 events
                const person1Events = await occurrenceRepository.getEventsForPerson(team.id, person1Id)
                expect(person1Events).toHaveLength(2)
                const person1EventNames = person1Events.map((e) => e.event_name).sort()
                expect(person1EventNames).toEqual(['$identify', '$pageview'])

                // Verify person2 has exactly 2 events
                const person2Events = await occurrenceRepository.getEventsForPerson(team.id, person2Id)
                expect(person2Events).toHaveLength(2)
                const person2EventNames = person2Events.map((e) => e.event_name).sort()
                expect(person2EventNames).toEqual(['$pageview', 'custom_event'])
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

            // Spy on the write methods to ensure they're never called when Cassandra is disabled
            const writeCountersSpy = jest.spyOn(processor as any, 'writeBehavioralCounters')
            const writeOccurrencesSpy = jest.spyOn(processor as any, 'writePersonEventOccurrences')

            // Act
            await processor.processBatch([behavioralEvent])

            // Assert - write methods should never be called when Cassandra is disabled
            expect(writeCountersSpy).toHaveBeenCalledTimes(0)
            expect(writeOccurrencesSpy).toHaveBeenCalledTimes(0)

            // Double-check repositories are still null
            expect(processor.getBehavioralCounterRepository()).toBeNull()
            expect(processor.getPersonEventOccurrenceRepository()).toBeNull()
        })
    })
})
