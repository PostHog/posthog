import { Message } from 'node-rdkafka'

import { KAFKA_CDP_AGGREGATION_WRITER_EVENTS } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub } from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
import { sanitizeString } from '../../utils/db/utils'
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
        // Deduplicate person performed events
        const deduplicatedPersonEvents = this.deduplicatePersonPerformedEvents(parsedBatch.personPerformedEvents)

        // Aggregate behavioural filter matched events
        const aggregatedBehaviouralEvents = this.aggregateBehaviouralFilterMatchedEvents(
            parsedBatch.behaviouralFilterMatchedEvents
        )

        // This will write both arrays in one transaction
        await this.writeToPostgres(deduplicatedPersonEvents, aggregatedBehaviouralEvents)
    }

    // Helper to build person events CTE using unnest
    private buildPersonEventsCTE(
        personEvents: PersonEventPayload[],
        paramOffset: number
    ): { cte: string; params: any[] } {
        const cte = `person_inserts AS (
            INSERT INTO person_performed_events_partitioned (team_id, person_id, event_name)
            SELECT * FROM unnest($${paramOffset}::int[], $${paramOffset + 1}::uuid[], $${paramOffset + 2}::text[])
            ON CONFLICT (team_id, person_id, event_name) DO NOTHING
            RETURNING 1
        )`

        const params = [
            personEvents.map((e) => e.teamId),
            personEvents.map((e) => e.personId),
            personEvents.map((e) => sanitizeString(e.eventName)),
        ]

        return { cte, params }
    }

    // Helper to build behavioural events CTE using unnest
    private buildBehaviouralEventsCTE(
        behaviouralEvents: AggregatedBehaviouralEvent[],
        paramOffset: number
    ): { cte: string; params: any[] } {
        const cte = `behavioural_inserts AS (
            INSERT INTO behavioural_filter_matched_events_partitioned (team_id, person_id, filter_hash, date, counter)
            SELECT * FROM unnest($${paramOffset}::int[], $${paramOffset + 1}::uuid[], $${paramOffset + 2}::text[], $${paramOffset + 3}::date[], $${paramOffset + 4}::int[])
            ON CONFLICT (team_id, person_id, filter_hash, date) 
            DO UPDATE SET counter = behavioural_filter_matched_events_partitioned.counter + EXCLUDED.counter
            RETURNING 1
        )`

        const params = [
            behaviouralEvents.map((e) => e.teamId),
            behaviouralEvents.map((e) => e.personId),
            behaviouralEvents.map((e) => sanitizeString(e.filterHash)),
            behaviouralEvents.map((e) => sanitizeString(e.date)),
            behaviouralEvents.map((e) => e.counter),
        ]

        return { cte, params }
    }

    // Write both event types to postgres in a single query
    private async writeToPostgres(
        personEvents: PersonEventPayload[],
        behaviouralEvents: AggregatedBehaviouralEvent[]
    ): Promise<void> {
        if (personEvents.length === 0 && behaviouralEvents.length === 0) {
            return
        }

        let query = ''
        try {
            const ctes: string[] = []
            const allParams: any[] = []
            let paramOffset = 1

            // Add CTEs for each event type
            if (personEvents.length > 0) {
                const { cte, params } = this.buildPersonEventsCTE(personEvents, paramOffset)
                ctes.push(cte)
                allParams.push(...params)
                paramOffset += params.length // person events use 3 array parameters
            }
            if (behaviouralEvents.length > 0) {
                const { cte, params } = this.buildBehaviouralEventsCTE(behaviouralEvents, paramOffset)
                ctes.push(cte)
                allParams.push(...params)
                // No need to update paramOffset here since we're done
            }

            // Build and execute the single combined query with parameters
            query = `WITH ${ctes.join(', ')} SELECT 1`
            await this.hub.postgres.query(PostgresUse.COUNTERS_RW, query, allParams, 'counters-batch-upsert')
        } catch (error: any) {
            logger.error('Failed to write to COUNTERS postgres', {
                error: error.message,
                errorCode: error.code,
                query: query,
                personEventsCount: personEvents.length,
                behaviouralEventsCount: behaviouralEvents.length,
            })
            throw error
        }
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
                await this.processBatch(parsedBatch)
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
