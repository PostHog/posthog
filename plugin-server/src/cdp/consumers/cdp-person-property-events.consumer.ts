import { Message } from 'node-rdkafka'
import { Histogram } from 'prom-client'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import {
    RealtimeSupportedFilter,
    RealtimeSupportedFilterManagerCDP,
} from '~/utils/realtime-supported-filter-manager-cdp'

import { KAFKA_CDP_CLICKHOUSE_PREFILTERED_PERSON_PROPERTIES, KAFKA_PERSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { ClickHousePerson, HealthCheckResult, Hub } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { ProducedPersonPropertyEvent } from '../types-person-property'
import { execHog } from '../utils/hog-exec'
import { CdpConsumerBase } from './cdp-base.consumer'

export const histogramPersonPropertyBatchProcessingSteps = new Histogram({
    name: 'cdp_person_property_batch_processing_steps_duration_ms',
    help: 'Time spent in different person property batch processing steps',
    labelNames: ['step'],
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
})

export class CdpPersonPropertyEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpPersonPropertyEventsConsumer'
    private kafkaConsumer: KafkaConsumer
    private realtimeSupportedFilterManager: RealtimeSupportedFilterManagerCDP

    constructor(hub: Hub, topic: string = KAFKA_PERSON, groupId: string = 'cdp-person-property-events-consumer') {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
        this.realtimeSupportedFilterManager = new RealtimeSupportedFilterManagerCDP(hub.db.postgres)
    }

    @instrumented('cdpPersonPropertyEventsConsumer.publishEvents')
    private async publishEvents(events: ProducedPersonPropertyEvent[]): Promise<void> {
        if (!this.kafkaProducer || events.length === 0) {
            return
        }

        try {
            const messages = events.map((event) => ({
                value: JSON.stringify(event.payload),
                key: event.key,
            }))

            await this.kafkaProducer.queueMessages({
                topic: KAFKA_CDP_CLICKHOUSE_PREFILTERED_PERSON_PROPERTIES,
                messages,
            })
        } catch (error) {
            logger.error('Error publishing person property events', {
                error,
                queueLength: events.length,
            })
            // Don't clear queue on error - messages will be retried with next batch
        }
    }

    // Evaluate if person matches person property filter using bytecode execution
    private async evaluatePersonAgainstRealtimeSupportedFilter(
        person: ClickHousePerson,
        filter: RealtimeSupportedFilter
    ): Promise<boolean> {
        if (!filter.bytecode) {
            return false
        }

        try {
            // Convert person to filter globals format
            const personProperties = parseJSON(person.properties)

            const globals = {
                person: {
                    id: person.id,
                    properties: personProperties,
                },
                project: {
                    id: person.team_id,
                },
            }

            const { execResult } = await execHog(filter.bytecode, {
                globals,
            })

            return execResult?.result ?? false
        } catch (error) {
            logger.error('Error executing person property filter bytecode', {
                conditionHash: filter.conditionHash,
                cohortId: filter.cohort_id,
                personId: person.id,
                error,
            })
            return false
        }
    }

    // Parse Kafka batch and create person property evaluation events
    @instrumented('cdpPersonPropertyEventsConsumer.handleEachBatch.parseKafkaBatch')
    public async _parseKafkaBatch(messages: Message[]): Promise<ProducedPersonPropertyEvent[]> {
        return await this.runWithHeartbeat(async () => {
            const events: ProducedPersonPropertyEvent[] = []

            // Step 1: Parse all messages and group by team_id
            const personsByTeam = new Map<number, ClickHousePerson[]>()

            // Parse and group persons by team
            for (const message of messages) {
                try {
                    const person = parseJSON(message.value!.toString()) as ClickHousePerson

                    if (!personsByTeam.has(person.team_id)) {
                        personsByTeam.set(person.team_id, [])
                    }
                    personsByTeam.get(person.team_id)!.push(person)
                } catch (e) {
                    logger.error('Error parsing person message', e)
                }
            }

            // Step 2: Fetch all realtime supported filters for all teams in one query
            const teamIds = Array.from(personsByTeam.keys())
            const filtersByTeam = await this.realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeams(teamIds)

            // Step 3: Process each team's persons with their realtime supported filters
            for (const [teamId, teamPersons] of Array.from(personsByTeam.entries())) {
                try {
                    const allFilters = filtersByTeam[String(teamId)] || []

                    // Only process person property filters
                    const filters = allFilters.filter((f) => f.filter_type === 'person_property')

                    if (filters.length === 0) {
                        // Skip teams with no person property filters
                        continue
                    }

                    // Process each person for this team
                    for (const person of teamPersons) {
                        // Convert timestamp to ClickHouse DateTime64(6) format
                        // The person record doesn't have an event timestamp, so we use current time
                        const evaluationTimestamp = new Date().toISOString().replace('T', ' ').replace('Z', '')

                        // Evaluate person against each realtime supported filter for this team
                        for (const filter of filters) {
                            const matches = await this.evaluatePersonAgainstRealtimeSupportedFilter(person, filter)

                            // CRITICAL: Always emit - both matches AND non-matches
                            // Person properties are mutable state, need to track changes
                            const personPropertyEvent: ProducedPersonPropertyEvent = {
                                key: person.id,
                                payload: {
                                    person_id: person.id,
                                    team_id: person.team_id,
                                    evaluation_timestamp: evaluationTimestamp,
                                    condition: filter.conditionHash,
                                    matches: matches ? 1 : 0, // 1 = match, 0 = no match
                                    source: `cohort_filter_${filter.conditionHash}`,
                                },
                            }

                            events.push(personPropertyEvent)
                        }
                    }
                } catch (e) {
                    logger.error('Error processing team persons', { teamId, error: e })
                }
            }
            return events
        })
    }

    public async start(): Promise<void> {
        await super.start()

        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpConsumer.handleEachBatch', async () => {
                const events = await this._parseKafkaBatch(messages)
                // Publish events in background
                const backgroundTask = this.publishEvents(events).catch((error) => {
                    throw new Error(`Failed to publish person property events: ${error.message}`)
                })

                return { backgroundTask }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping person property events consumer...')
        await this.kafkaConsumer.disconnect()

        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Person property events consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
