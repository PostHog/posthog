import { Message } from 'node-rdkafka'

import { KAFKA_CDP_AGGREGATION_WRITER_EVENTS } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub } from '../../types'
import { PostgresUse } from '../../utils/db/postgres'
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

    // Parse messages grouped by partition to maintain isolation
    public async _parseKafkaBatchByPartition(messages: Message[]): Promise<Map<number, ParsedBatch>> {
        return await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpAggregationWriterConsumer.handleEachBatch.parseKafkaMessagesByPartition`,
                func: () => {
                    const batchesByPartition = new Map<number, ParsedBatch>()

                    messages.forEach((message) => {
                        try {
                            const partition = message.partition
                            if (!batchesByPartition.has(partition)) {
                                batchesByPartition.set(partition, {
                                    personPerformedEvents: [],
                                    behaviouralFilterMatchedEvents: [],
                                })
                            }

                            const batch = batchesByPartition.get(partition)!
                            const event = parseJSON(message.value!.toString()) as ProducedEvent

                            if (event.payload.type === 'person-performed-event') {
                                batch.personPerformedEvents.push(event.payload as PersonEventPayload)
                            } else if (event.payload.type === 'behavioural-filter-match-event') {
                                batch.behaviouralFilterMatchedEvents.push(event.payload as CohortFilterPayload)
                            } else {
                                logger.warn('Unknown event type', { type: (event.payload as any).type })
                            }
                        } catch (e) {
                            logger.error('Error parsing message', e)
                        }
                    })

                    return Promise.resolve(batchesByPartition)
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

    // Helper to build person events CTE
    private buildPersonEventsCTE(personEvents: PersonEventPayload[]): string {
        const values = personEvents
            .map((event) => `(${event.teamId}, '${event.personId}', '${event.eventName.replace(/'/g, "''")}')`)
            .join(',')

        return `person_inserts AS (
            INSERT INTO person_performed_events (team_id, person_id, event_name)
            VALUES ${values}
            ON CONFLICT (team_id, person_id, event_name) DO NOTHING
            RETURNING 1
        )`
    }

    // Helper to build behavioural events CTE (expects pre-sorted events)
    private buildBehaviouralEventsCTE(behaviouralEvents: AggregatedBehaviouralEvent[]): string {
        const values = behaviouralEvents
            .map(
                (event) =>
                    `(${event.teamId}, '${event.personId}', '${event.filterHash}', '${event.date}', ${event.counter})`
            )
            .join(',')

        return `behavioural_inserts AS (
            INSERT INTO behavioural_filter_matched_events (team_id, person_id, filter_hash, date, counter)
            VALUES ${values}
            ON CONFLICT (team_id, person_id, filter_hash, date) 
            DO UPDATE SET counter = behavioural_filter_matched_events.counter + EXCLUDED.counter
            RETURNING 1
        )`
    }

    // Write both event types to postgres with retry logic for deadlocks
    private async writeToPostgres(
        personEvents: PersonEventPayload[],
        behaviouralEvents: AggregatedBehaviouralEvent[]
    ): Promise<void> {
        if (personEvents.length === 0 && behaviouralEvents.length === 0) {
            return
        }

        const MAX_RETRIES = 3
        const INITIAL_BACKOFF_MS = 50

        for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
            try {
                const ctes: string[] = []

                // Add CTEs for each event type
                if (personEvents.length > 0) {
                    ctes.push(this.buildPersonEventsCTE(personEvents))
                }
                if (behaviouralEvents.length > 0) {
                    // Sort behavioural events to ensure consistent lock ordering
                    const sortedBehaviouralEvents = [...behaviouralEvents].sort((a, b) => {
                        const keyA = `${a.teamId}:${a.personId}:${a.filterHash}:${a.date}`
                        const keyB = `${b.teamId}:${b.personId}:${b.filterHash}:${b.date}`
                        return keyA.localeCompare(keyB)
                    })
                    ctes.push(this.buildBehaviouralEventsCTE(sortedBehaviouralEvents))
                }

                // Build and execute the single combined query
                const query = `WITH ${ctes.join(', ')} SELECT 1`
                await this.hub.postgres.query(PostgresUse.COUNTERS_RW, query, undefined, 'counters-batch-upsert')

                // Success - exit retry loop
                return
            } catch (error: any) {
                const isDeadlock = error?.code === '40P01'
                const isLastAttempt = attempt === MAX_RETRIES - 1

                if (isDeadlock && !isLastAttempt) {
                    // Exponential backoff with jitter for deadlock retries
                    const backoffMs = INITIAL_BACKOFF_MS * Math.pow(2, attempt) + Math.random() * 50
                    logger.warn('Deadlock detected, retrying with backoff', {
                        attempt: attempt + 1,
                        maxRetries: MAX_RETRIES,
                        backoffMs,
                        personEventsCount: personEvents.length,
                        behaviouralEventsCount: behaviouralEvents.length,
                    })
                    await new Promise((resolve) => setTimeout(resolve, backoffMs))
                } else {
                    // Non-deadlock error or final attempt - throw
                    logger.error('Failed to write to COUNTERS postgres', {
                        error,
                        attempt: attempt + 1,
                        isDeadlock,
                        personEventsCount: personEvents.length,
                        behaviouralEventsCount: behaviouralEvents.length,
                    })
                    throw error
                }
            }
        }
    }

    // Ensure counters tables exist on startup
    private async ensureCountersTables(): Promise<void> {
        try {
            await this.hub.postgres.query(
                PostgresUse.COUNTERS_RW,
                `
                -- Table for person performed events
                CREATE TABLE IF NOT EXISTS person_performed_events (
                    team_id INTEGER NOT NULL,
                    person_id UUID NOT NULL,
                    event_name TEXT NOT NULL,
                    PRIMARY KEY (team_id, person_id, event_name)
                );

                -- Index for efficient lookups by team_id and person_id
                CREATE INDEX IF NOT EXISTS idx_person_performed_events_team_person 
                ON person_performed_events (team_id, person_id);

                -- Table for behavioural filter matched events
                CREATE TABLE IF NOT EXISTS behavioural_filter_matched_events (
                    team_id INTEGER NOT NULL,
                    person_id UUID NOT NULL,
                    filter_hash TEXT NOT NULL,
                    date DATE NOT NULL,
                    counter INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (team_id, person_id, filter_hash, date)
                );

                -- Index for queries by just team_id and person_id
                CREATE INDEX IF NOT EXISTS idx_behavioural_filter_team_person 
                ON behavioural_filter_matched_events (team_id, person_id);
                `,
                undefined,
                'ensure-counters-tables'
            )
            logger.info('✅', 'Counters database tables ensured')
        } catch (error) {
            logger.error('Failed to ensure counters tables', { error })
            throw error
        }
    }

    public async start(): Promise<void> {
        await super.start()

        // Ensure counters tables exist before starting to consume
        await this.ensureCountersTables()

        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            // Group messages by partition
            const partitions = new Set(messages.map((m) => m.partition))

            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
                partitions: Array.from(partitions),
            })

            return await this.runInstrumented('handleEachBatch', async () => {
                const batchesByPartition = await this._parseKafkaBatchByPartition(messages)

                // Process each partition's batch sequentially to maintain isolation
                // This ensures events from the same partition (same person) are never processed concurrently
                const backgroundTask = (async () => {
                    for (const [partition, parsedBatch] of batchesByPartition) {
                        try {
                            await this.processBatch(parsedBatch)
                            logger.debug('Processed partition batch', {
                                partition,
                                personEvents: parsedBatch.personPerformedEvents.length,
                                behaviouralEvents: parsedBatch.behaviouralFilterMatchedEvents.length,
                            })
                        } catch (error: any) {
                            // Log error but continue with other partitions
                            logger.error(`Failed to process partition ${partition}`, { error })
                            throw error
                        }
                    }
                })().catch((error) => {
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
