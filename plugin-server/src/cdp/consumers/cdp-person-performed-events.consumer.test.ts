import { getFirstTeam, resetTestDatabase } from '../../../tests/helpers/sql'
import { CdpPersonPerformedEvent, Hub, Team } from '../../types'
import { closeHub, createHub } from '../../utils/db/hub'
import { CdpPersonPerformedEventsConsumer } from './cdp-person-performed-events.consumer'

class TestableCdpPersonPerformedEventsConsumer extends CdpPersonPerformedEventsConsumer {
    // Expose protected methods for testing
    public async testProcessEvent(event: CdpPersonPerformedEvent) {
        return this.processEvent(event)
    }

    public testDeduplicateEvents(events: CdpPersonPerformedEvent[]) {
        return this.deduplicateEvents(events)
    }

    public testGetCacheKey(event: CdpPersonPerformedEvent) {
        return this.getCacheKey(event)
    }

    public testEvictCacheEntries() {
        return this.evictCacheEntries()
    }

    public getCacheSize() {
        return this.deduplicationCache.size
    }

    public clearCache() {
        this.deduplicationCache.clear()
    }

    public setCacheSize(size: number) {
        this.maxCacheSize = size
    }

    public setCacheEvictionBatchSize(size: number) {
        this.cacheEvictionBatchSize = size
    }
}

jest.setTimeout(10_000)

describe('CdpPersonPerformedEventsConsumer', () => {
    let processor: TestableCdpPersonPerformedEventsConsumer
    let hub: Hub
    let team: Team

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub)
        processor = new TestableCdpPersonPerformedEventsConsumer(hub)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('message parsing', () => {
        it('should parse valid person performed event messages', async () => {
            const personId = '550e8400-e29b-41d4-a716-446655440000'
            const eventName = '$pageview'
            const messages = [
                {
                    value: Buffer.from(
                        JSON.stringify({
                            teamId: team.id,
                            personId,
                            eventName,
                        } as CdpPersonPerformedEvent)
                    ),
                } as any,
            ]

            // Parse messages
            const events = await processor._parseKafkaBatch(messages)

            // Verify parsed events
            expect(events).toHaveLength(1)
            expect(events[0]).toEqual({
                teamId: team.id,
                personId,
                eventName,
            })
        })

        it('should handle malformed JSON gracefully', async () => {
            const messages = [
                {
                    value: Buffer.from('invalid json'),
                } as any,
                {
                    value: Buffer.from(
                        JSON.stringify({
                            teamId: team.id,
                            personId: '550e8400-e29b-41d4-a716-446655440000',
                            eventName: '$pageview',
                        })
                    ),
                } as any,
            ]

            // Parse messages should not throw
            const events = await processor._parseKafkaBatch(messages)

            // Verify only valid message was parsed
            expect(events).toHaveLength(1)
            expect(events[0].eventName).toBe('$pageview')
        })
    })

    describe('event processing', () => {
        it('should process person performed events without errors', async () => {
            const event: CdpPersonPerformedEvent = {
                teamId: team.id,
                personId: '550e8400-e29b-41d4-a716-446655440000',
                eventName: '$pageview',
            }

            // Process event should not throw
            await expect(processor.testProcessEvent(event)).resolves.not.toThrow()
        })

        it('should process batch of events', async () => {
            const events: CdpPersonPerformedEvent[] = [
                {
                    teamId: team.id,
                    personId: '550e8400-e29b-41d4-a716-446655440000',
                    eventName: '$pageview',
                },
                {
                    teamId: team.id,
                    personId: '550e8400-e29b-41d4-a716-446655440001',
                    eventName: '$identify',
                },
                {
                    teamId: 999,
                    personId: '550e8400-e29b-41d4-a716-446655440002',
                    eventName: 'custom_event',
                },
            ]

            // Process batch should not throw
            await expect(processor.processBatch(events)).resolves.not.toThrow()
        })

        it('should handle empty batch', async () => {
            const events: CdpPersonPerformedEvent[] = []

            // Process empty batch should not throw
            await expect(processor.processBatch(events)).resolves.not.toThrow()
        })
    })

    describe('deduplication cache', () => {
        it('should generate consistent cache keys', () => {
            const event: CdpPersonPerformedEvent = {
                teamId: 123,
                personId: '550e8400-e29b-41d4-a716-446655440000',
                eventName: '$pageview',
            }

            const key1 = processor.testGetCacheKey(event)
            const key2 = processor.testGetCacheKey(event)

            expect(key1).toBe(key2)
            expect(key1).toBe('123:550e8400-e29b-41d4-a716-446655440000:$pageview')
        })

        it('should deduplicate identical events', () => {
            const event: CdpPersonPerformedEvent = {
                teamId: team.id,
                personId: '550e8400-e29b-41d4-a716-446655440000',
                eventName: '$pageview',
            }

            // First batch with same event twice
            const events = [event, { ...event }]
            const deduplicatedEvents = processor.testDeduplicateEvents(events)

            // Should only return one event (first occurrence)
            expect(deduplicatedEvents).toHaveLength(1)
            expect(processor.getCacheSize()).toBe(1)
        })

        it('should not deduplicate different events', () => {
            const events: CdpPersonPerformedEvent[] = [
                {
                    teamId: team.id,
                    personId: '550e8400-e29b-41d4-a716-446655440000',
                    eventName: '$pageview',
                },
                {
                    teamId: team.id,
                    personId: '550e8400-e29b-41d4-a716-446655440001',
                    eventName: '$pageview',
                },
                {
                    teamId: team.id,
                    personId: '550e8400-e29b-41d4-a716-446655440000',
                    eventName: '$identify',
                },
            ]

            const deduplicatedEvents = processor.testDeduplicateEvents(events)

            // All events should be unique
            expect(deduplicatedEvents).toHaveLength(3)
            expect(processor.getCacheSize()).toBe(3)
        })

        it('should track cache hits and misses', () => {
            const event: CdpPersonPerformedEvent = {
                teamId: team.id,
                personId: '550e8400-e29b-41d4-a716-446655440000',
                eventName: '$pageview',
            }

            // First deduplication - should be cache miss
            processor.testDeduplicateEvents([event])

            // Second deduplication with same event - should be cache hit
            const deduplicatedEvents = processor.testDeduplicateEvents([event])

            expect(deduplicatedEvents).toHaveLength(0) // Event was duplicate
        })

        it('should evict cache entries when limit is reached', () => {
            // Set a small cache size for testing
            processor.setCacheSize(3)
            processor.setCacheEvictionBatchSize(1)

            const events: CdpPersonPerformedEvent[] = [
                { teamId: team.id, personId: 'person1', eventName: 'event1' },
                { teamId: team.id, personId: 'person2', eventName: 'event2' },
                { teamId: team.id, personId: 'person3', eventName: 'event3' },
            ]

            // Fill up the cache
            processor.testDeduplicateEvents(events)
            expect(processor.getCacheSize()).toBe(3)

            // Add one more event, should trigger eviction
            const newEvent = { teamId: team.id, personId: 'person4', eventName: 'event4' }
            processor.testDeduplicateEvents([newEvent])

            // Cache should still be at max size (3)
            expect(processor.getCacheSize()).toBe(3)
        })

        it('should process mixed batch with duplicates and new events', async () => {
            const event1: CdpPersonPerformedEvent = {
                teamId: team.id,
                personId: '550e8400-e29b-41d4-a716-446655440000',
                eventName: '$pageview',
            }
            const event2: CdpPersonPerformedEvent = {
                teamId: team.id,
                personId: '550e8400-e29b-41d4-a716-446655440001',
                eventName: '$identify',
            }

            // Process first batch
            await processor.processBatch([event1, event2])
            expect(processor.getCacheSize()).toBe(2)

            // Process second batch with one duplicate and one new event
            const event3: CdpPersonPerformedEvent = {
                teamId: team.id,
                personId: '550e8400-e29b-41d4-a716-446655440002',
                eventName: 'custom_event',
            }

            await processor.processBatch([event1, event3]) // event1 is duplicate
            expect(processor.getCacheSize()).toBe(3) // Should have event1, event2, event3
        })
    })
})
