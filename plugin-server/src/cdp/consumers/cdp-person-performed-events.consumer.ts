import { Message } from 'node-rdkafka'
import { Counter, Gauge, Histogram } from 'prom-client'

import { KAFKA_CDP_PERSON_PERFORMED_EVENT } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { runInstrumentedFunction } from '../../main/utils'
import { CdpPersonPerformedEvent, Hub } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { CdpConsumerBase } from './cdp-base.consumer'

export const histogramPersonPerformedEventProcessing = new Histogram({
    name: 'cdp_person_performed_event_processing_duration_ms',
    help: 'Time spent processing person performed events',
    labelNames: ['step'],
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
})

export const cacheOperationsTotal = new Counter({
    name: 'cdp_person_performed_event_cache_operations_total',
    help: 'Total number of cache operations performed',
    labelNames: ['operation', 'outcome'],
})

export const cacheHitRateGauge = new Counter({
    name: 'cdp_person_performed_event_cache_hit_rate_total',
    help: 'Total cache hits and misses for cache hit rate calculation',
    labelNames: ['type'],
})

export const cacheSizeGauge = new Gauge({
    name: 'cdp_person_performed_event_cache_size',
    help: 'Current number of entries in cache',
})

export class CdpPersonPerformedEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpPersonPerformedEventsConsumer'
    protected kafkaConsumer: KafkaConsumer
    protected deduplicationCache: Set<string> = new Set()
    protected maxCacheSize: number = 100000 // Cache for ~100k unique events
    protected cacheEvictionBatchSize: number = 10000 // Evict 10k entries when cache is full

    constructor(hub: Hub, groupId: string = 'cdp-person-performed-events-consumer') {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({
            groupId,
            topic: KAFKA_CDP_PERSON_PERFORMED_EVENT,
        })
    }

    public async processBatch(events: CdpPersonPerformedEvent[]): Promise<void> {
        return await this.runInstrumented('processBatch', async () => {
            if (!events.length) {
                return
            }

            logger.debug('Processing person performed events batch', {
                eventCount: events.length,
                teamIds: [...new Set(events.map((e) => e.teamId))],
                cacheSize: this.deduplicationCache.size,
            })

            // Time deduplication
            const deduplicationTimer = histogramPersonPerformedEventProcessing
                .labels({ step: 'deduplication' })
                .startTimer()

            // Deduplicate events before processing
            const deduplicatedEvents = this.deduplicateEvents(events)
            deduplicationTimer()

            if (deduplicatedEvents.length === 0) {
                logger.debug('All events in batch were duplicates')
                return
            }

            // Time event processing
            const eventProcessingTimer = histogramPersonPerformedEventProcessing
                .labels({ step: 'event_processing' })
                .startTimer()

            await Promise.all(deduplicatedEvents.map((event) => this.processEvent(event)))
            eventProcessingTimer()
        })
    }

    protected deduplicateEvents(events: CdpPersonPerformedEvent[]): CdpPersonPerformedEvent[] {
        const deduplicatedEvents: CdpPersonPerformedEvent[] = []

        for (const event of events) {
            const cacheKey = this.getCacheKey(event)

            if (this.deduplicationCache.has(cacheKey)) {
                cacheHitRateGauge.labels({ type: 'hit' }).inc()
                cacheOperationsTotal.labels({ operation: 'lookup', outcome: 'hit' }).inc()
            } else {
                cacheHitRateGauge.labels({ type: 'miss' }).inc()
                cacheOperationsTotal.labels({ operation: 'lookup', outcome: 'miss' }).inc()

                // Check cache size and evict if necessary
                if (this.deduplicationCache.size >= this.maxCacheSize) {
                    this.evictCacheEntries()
                }

                // Add to cache and include in deduplicated events
                this.deduplicationCache.add(cacheKey)
                cacheSizeGauge.inc()
                cacheOperationsTotal.labels({ operation: 'insert', outcome: 'success' }).inc()
                deduplicatedEvents.push(event)
            }
        }

        return deduplicatedEvents
    }

    protected getCacheKey(event: CdpPersonPerformedEvent): string {
        return `${event.teamId}:${event.personId}:${event.eventName}`
    }

    protected evictCacheEntries(): void {
        // Convert Set to Array, remove first N entries (FIFO eviction)
        const cacheEntries = Array.from(this.deduplicationCache)
        const entriesToEvict = cacheEntries.slice(0, this.cacheEvictionBatchSize)

        entriesToEvict.forEach((entry) => {
            this.deduplicationCache.delete(entry)
            cacheSizeGauge.dec()
        })

        cacheOperationsTotal.labels({ operation: 'evict', outcome: 'success' }).inc(entriesToEvict.length)
    }

    protected async processEvent(event: CdpPersonPerformedEvent): Promise<void> {
        try {
            await Promise.resolve()
            // TODO: Add postgres write logic here once analysis is done
        } catch (error) {
            logger.error('Error processing person performed event', {
                teamId: event.teamId,
                personId: event.personId,
                eventName: event.eventName,
                error,
            })
        }
    }

    // This consumer always parses from kafka
    public async _parseKafkaBatch(messages: Message[]): Promise<CdpPersonPerformedEvent[]> {
        return await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpPersonPerformedEventsConsumer.handleEachBatch.parseKafkaMessages`,
                func: () => {
                    const events: CdpPersonPerformedEvent[] = []

                    messages.forEach((message) => {
                        try {
                            const personPerformedEvent = parseJSON(message.value!.toString()) as CdpPersonPerformedEvent
                            events.push(personPerformedEvent)
                        } catch (e) {
                            logger.error('Error parsing person performed event message', e)
                        }
                    })

                    return Promise.resolve(events)
                },
            })
        )
    }

    public async start(): Promise<void> {
        await super.start()

        logger.info('🚀', `Starting ${this.name}...`)

        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await this.runInstrumented('handleEachBatch', async () => {
                const events = await this._parseKafkaBatch(messages)
                await this.processBatch(events)
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        await this.kafkaConsumer.disconnect()

        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy() {
        return this.kafkaConsumer.isHealthy()
    }
}
