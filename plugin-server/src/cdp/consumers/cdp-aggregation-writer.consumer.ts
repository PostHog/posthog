import { Message } from 'node-rdkafka'

import { KAFKA_CDP_AGGREGATION_WRITER_EVENTS } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { CdpConsumerBase } from './cdp-base.consumer'
import { CohortFilterPayload, PersonEventPayload, ProducedEvent } from './cdp-behavioural-events.consumer'

export interface ParsedBatch {
    personPerformedEvents: PersonEventPayload[]
    behaviouralFilterMatchedEvents: CohortFilterPayload[]
}
export interface AggregatedBehaviouralEvent extends CohortFilterPayload {
    counter: number
}

export type EventToWrite = PersonEventPayload | AggregatedBehaviouralEvent

export class CdpAggregationWriterConsumer extends CdpConsumerBase {
    protected name = 'CdpAggregationWriterConsumer'
    private kafkaConsumer: KafkaConsumer

    constructor(
        hub: Hub,
        topic: string = KAFKA_CDP_AGGREGATION_WRITER_EVENTS,
        groupId: string = 'cdp-aggregation-writer-consumer'
    ) {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
    }

    // Parse messages from Kafka and separate them into two arrays
    public async _parseKafkaBatch(messages: Message[]): Promise<ParsedBatch> {
        return await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpAggregationWriterConsumer.handleEachBatch.parseKafkaMessages`,
                func: () => {
                    const personPerformedEvents: PersonEventPayload[] = []
                    const behaviouralFilterMatchedEvents: CohortFilterPayload[] = []

                    messages.forEach((message) => {
                        try {
                            const event = parseJSON(message.value!.toString()) as ProducedEvent

                            if (event.payload.type === 'person-performed-event') {
                                personPerformedEvents.push(event.payload as PersonEventPayload)
                            } else if (event.payload.type === 'behavioural-filter-match-event') {
                                behaviouralFilterMatchedEvents.push(event.payload as CohortFilterPayload)
                            } else {
                                logger.warn('Unknown event type', { type: (event.payload as any).type })
                            }
                        } catch (e) {
                            logger.error('Error parsing message', e)
                        }
                    })

                    return Promise.resolve({
                        personPerformedEvents,
                        behaviouralFilterMatchedEvents,
                    })
                },
            })
        )
    }

    // Deduplicate person performed events (unique by teamId, personId, eventName)
    private deduplicatePersonPerformedEvents(events: PersonEventPayload[]): PersonEventPayload[] {
        const uniqueEventsMap = new Map<string, PersonEventPayload>()

        for (const event of events) {
            const key = `${event.teamId}:${event.personId}:${event.eventName}`
            if (!uniqueEventsMap.has(key)) {
                uniqueEventsMap.set(key, { ...event })
            }
        }

        return Array.from(uniqueEventsMap.values())
    }

    // Aggregate behavioural filter matched events with counter (aggregate by teamId, personId, filterHash, date)
    private aggregateBehaviouralFilterMatchedEvents(events: CohortFilterPayload[]): AggregatedBehaviouralEvent[] {
        const aggregatedEventsMap = new Map<string, AggregatedBehaviouralEvent>()

        for (const event of events) {
            const key = `${event.teamId}:${event.personId}:${event.filterHash}:${event.date}`
            const existing = aggregatedEventsMap.get(key)

            if (existing) {
                existing.counter += 1
            } else {
                aggregatedEventsMap.set(key, {
                    ...event,
                    counter: 1,
                })
            }
        }

        return Array.from(aggregatedEventsMap.values())
    }

    // Process batch by aggregating and writing to postgres
    private async processBatch(parsedBatch: ParsedBatch): Promise<void> {
        const eventsToWrite: EventToWrite[] = []

        // Deduplicate person performed events
        const deduplicatedPersonEvents = this.deduplicatePersonPerformedEvents(parsedBatch.personPerformedEvents)
        eventsToWrite.push(...deduplicatedPersonEvents)

        // Aggregate behavioural filter matched events
        const aggregatedBehaviouralEvents = this.aggregateBehaviouralFilterMatchedEvents(
            parsedBatch.behaviouralFilterMatchedEvents
        )
        eventsToWrite.push(...aggregatedBehaviouralEvents)

        logger.info('Processing batch', {
            originalPersonPerformedEventsCount: parsedBatch.personPerformedEvents.length,
            deduplicatedPersonPerformedEventsCount: deduplicatedPersonEvents.length,
            originalBehaviouralFilterMatchedEventsCount: parsedBatch.behaviouralFilterMatchedEvents.length,
            aggregatedBehaviouralFilterMatchedEventsCount: aggregatedBehaviouralEvents.length,
            totalEventsToWrite: eventsToWrite.length,
        })

        // TODO: Implement batch write to postgres using efficient upsert queries
        // This will write all eventsToWrite in one transaction
        return Promise.resolve()
    }

    public async start(): Promise<void> {
        await super.start()

        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await this.runInstrumented('handleEachBatch', async () => {
                const parsedBatch = await this._parseKafkaBatch(messages)

                // Process the batch (aggregate and write to postgres)
                const backgroundTask = this.processBatch(parsedBatch).catch((error) => {
                    throw new Error(`Failed to process aggregation batch: ${error.message}`)
                })

                return { backgroundTask }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping aggregation writer consumer...')
        await this.kafkaConsumer.disconnect()

        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Aggregation writer consumer stopped!')
    }

    public isHealthy() {
        return this.kafkaConsumer.isHealthy()
    }
}
