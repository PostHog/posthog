import { Message } from 'node-rdkafka'
import { Histogram } from 'prom-client'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import {
    RealtimeSupportedFilter,
    RealtimeSupportedFilterManagerCDP,
} from '~/utils/realtime-supported-filter-manager-cdp'

import {
    KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
    KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS,
    KAFKA_EVENTS_JSON,
} from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { HogFunctionFilterGlobals } from '../types'
import { ProducedPersonPropertiesEvent } from '../types-person-properties'
import { execHog } from '../utils/hog-exec'
import { convertClickhouseRawEventToFilterGlobals } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseHub } from './cdp-base.consumer'

export type PersonPropertyFilterGlobals = {
    person: {
        id?: string
        properties: Record<string, any>
    }
    project: {
        id: number
    }
}

export type PreCalculatedEvent = {
    uuid: string // event uuid
    team_id: number
    person_id: string
    distinct_id: string
    condition: string // hash of the filter bytecode
    source: string
}

export type ProducedEvent = {
    key: string
    payload: PreCalculatedEvent
}

export const histogramBatchProcessingSteps = new Histogram({
    name: 'cdp_precalculated_filters_batch_processing_steps_duration_ms',
    help: 'Time spent in different batch processing steps',
    labelNames: ['step'],
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
})

/**
 * Hub type for CdpPrecalculatedFiltersConsumer.
 */
export type CdpPrecalculatedFiltersConsumerHub = CdpConsumerBaseHub

export class CdpPrecalculatedFiltersConsumer extends CdpConsumerBase<CdpPrecalculatedFiltersConsumerHub> {
    protected name = 'CdpPrecalculatedFiltersConsumer'
    private eventKafkaConsumer: KafkaConsumer
    private realtimeSupportedFilterManager: RealtimeSupportedFilterManagerCDP

    constructor(hub: CdpPrecalculatedFiltersConsumerHub) {
        super(hub)
        this.eventKafkaConsumer = new KafkaConsumer({
            groupId: 'cdp-precalculated-filters-consumer',
            topic: KAFKA_EVENTS_JSON,
        })
        this.realtimeSupportedFilterManager = new RealtimeSupportedFilterManagerCDP(hub.postgres)
    }

    @instrumented('cdpPrecalculatedFiltersConsumer.publishBehavioralEvents')
    private async publishBehavioralEvents(events: ProducedEvent[]): Promise<void> {
        if (!this.kafkaProducer || events.length === 0) {
            return
        }

        try {
            const messages = events.map((event) => ({
                value: JSON.stringify(event.payload),
                key: event.key,
            }))

            await this.kafkaProducer.queueMessages({ topic: KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS, messages })
        } catch (error) {
            logger.error('Error publishing behavioral events', {
                error,
                queueLength: events.length,
            })
            throw error
        }
    }

    @instrumented('cdpPrecalculatedFiltersConsumer.publishPersonPropertyEvents')
    private async publishPersonPropertyEvents(events: ProducedPersonPropertiesEvent[]): Promise<void> {
        if (!this.kafkaProducer || events.length === 0) {
            return
        }

        try {
            const messages = events.map((event) => ({
                value: JSON.stringify(event.payload),
                key: event.key,
            }))

            await this.kafkaProducer.queueMessages({
                topic: KAFKA_CDP_CLICKHOUSE_PRECALCULATED_PERSON_PROPERTIES,
                messages,
            })
        } catch (error) {
            logger.error('Error publishing person property events', {
                error,
                queueLength: events.length,
            })
            throw error
        }
    }

    // Evaluate if event matches behavioral filter using bytecode execution
    private async evaluateEventAgainstRealtimeSupportedFilter(
        filterGlobals: HogFunctionFilterGlobals,
        filter: RealtimeSupportedFilter
    ): Promise<boolean> {
        if (!filter.bytecode) {
            logger.error('Missing bytecode for behavioral filter', {
                conditionHash: filter.conditionHash,
                cohortId: filter.cohort_id,
            })
            return false
        }

        try {
            const { execResult } = await execHog(filter.bytecode, {
                globals: filterGlobals,
            })

            return execResult?.result ?? false
        } catch (error) {
            logger.error('Error executing behavioral filter bytecode', {
                conditionHash: filter.conditionHash,
                cohortId: filter.cohort_id,
                error,
            })
            return false
        }
    }

    // Evaluate person properties against filter using bytecode execution
    // Used for person_properties field from events
    private async evaluatePersonPropertiesAgainstFilter(
        personGlobals: PersonPropertyFilterGlobals,
        filter: RealtimeSupportedFilter
    ): Promise<boolean> {
        if (!filter.bytecode) {
            logger.error('Missing bytecode for person property filter', {
                conditionHash: filter.conditionHash,
                cohortId: filter.cohort_id,
            })
            return false
        }

        try {
            const { execResult } = await execHog(filter.bytecode, {
                globals: personGlobals,
            })

            return execResult?.result ?? false
        } catch (error) {
            logger.error('Error executing person property filter bytecode', {
                conditionHash: filter.conditionHash,
                cohortId: filter.cohort_id,
                personId: personGlobals.person.id,
                error,
            })
            return false
        }
    }

    // This consumer parses events from kafka and evaluates both behavioral and person property filters
    @instrumented('cdpPrecalculatedFiltersConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<{
        precalculatedEvents: ProducedEvent[]
        precalculatedPersonProperties: ProducedPersonPropertiesEvent[]
    }> {
        return await this.runWithHeartbeat(async () => {
            const behavioralEvents: ProducedEvent[] = []
            const personPropertyEvents: ProducedPersonPropertiesEvent[] = []

            // Step 1: Parse all messages and group by team_id
            const eventsByTeam = new Map<number, RawClickHouseEvent[]>()

            // Parse and group events by team
            for (const message of messages) {
                try {
                    const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                    if (!clickHouseEvent.person_id) {
                        logger.error('Event missing person_id', {
                            teamId: clickHouseEvent.team_id,
                            event: clickHouseEvent.event,
                            uuid: clickHouseEvent.uuid,
                        })
                        continue // Skip events without person_id
                    }

                    if (!eventsByTeam.has(clickHouseEvent.team_id)) {
                        eventsByTeam.set(clickHouseEvent.team_id, [])
                    }
                    eventsByTeam.get(clickHouseEvent.team_id)!.push(clickHouseEvent)
                } catch (e) {
                    logger.error('Error parsing message', e)
                }
            }

            // Step 2: Fetch all realtime supported filters for all teams in one query
            const teamIds = Array.from(eventsByTeam.keys())
            const filtersByTeam = await this.realtimeSupportedFilterManager.getRealtimeSupportedFiltersForTeams(teamIds)

            // Step 3: Process each team's events with their realtime supported filters
            for (const [teamId, teamEvents] of Array.from(eventsByTeam.entries())) {
                try {
                    const filters = filtersByTeam[String(teamId)]
                    if (!filters) {
                        continue
                    }

                    const { behavioral: behavioralFilters, person_property: personPropertyFilters } = filters

                    if (behavioralFilters.length === 0 && personPropertyFilters.length === 0) {
                        // Skip teams with no filters
                        continue
                    }

                    // Process each event for this team
                    for (const clickHouseEvent of teamEvents) {
                        // Convert to filter globals for filter evaluation
                        const filterGlobals = convertClickhouseRawEventToFilterGlobals(clickHouseEvent)

                        // Evaluate behavioral filters
                        for (const filter of behavioralFilters) {
                            const matches = await this.evaluateEventAgainstRealtimeSupportedFilter(
                                filterGlobals,
                                filter
                            )

                            // Only publish if event matches the filter (don't publish non-matches)
                            if (matches) {
                                const preCalculatedEvent: ProducedEvent = {
                                    key: filterGlobals.distinct_id,
                                    payload: {
                                        uuid: filterGlobals.uuid,
                                        team_id: clickHouseEvent.team_id,
                                        person_id: clickHouseEvent.person_id!,
                                        distinct_id: filterGlobals.distinct_id,
                                        condition: filter.conditionHash,
                                        source: `cohort_filter_${filter.conditionHash}`,
                                    },
                                }

                                behavioralEvents.push(preCalculatedEvent)
                            }
                        }

                        // Evaluate person property filters using person_properties from the event
                        if (personPropertyFilters.length > 0 && clickHouseEvent.person_properties) {
                            const personProperties = parseJSON(clickHouseEvent.person_properties)

                            const personGlobals: PersonPropertyFilterGlobals = {
                                person: {
                                    id: clickHouseEvent.person_id,
                                    properties: personProperties,
                                },
                                project: {
                                    id: clickHouseEvent.team_id,
                                },
                            }

                            for (const filter of personPropertyFilters) {
                                const matches = await this.evaluatePersonPropertiesAgainstFilter(personGlobals, filter)

                                // CRITICAL: Always emit - both matches AND non-matches
                                // Person properties are mutable state, need to track changes
                                const personPropertyEvent: ProducedPersonPropertiesEvent = {
                                    key: clickHouseEvent.distinct_id,
                                    payload: {
                                        distinct_id: clickHouseEvent.distinct_id,
                                        person_id: clickHouseEvent.person_id!,
                                        team_id: clickHouseEvent.team_id,
                                        condition: filter.conditionHash,
                                        matches: matches,
                                        source: `cohort_filter_${filter.conditionHash}`,
                                    },
                                }

                                personPropertyEvents.push(personPropertyEvent)
                            }
                        }
                    }
                } catch (e) {
                    logger.error('Error processing team events', { teamId, error: e })
                }
            }
            return { precalculatedEvents: behavioralEvents, precalculatedPersonProperties: personPropertyEvents }
        })
    }

    public async start(): Promise<void> {
        await super.start()

        await this.eventKafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling event batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpPrecalculatedFiltersConsumer.handleEventBatch', async () => {
                const { precalculatedEvents, precalculatedPersonProperties } = await this._parseKafkaBatch(messages)

                // Publish both types of events in parallel
                const backgroundTask = Promise.all([
                    this.publishBehavioralEvents(precalculatedEvents).catch((error) => {
                        throw new Error(`Failed to publish behavioral events: ${error.message}`)
                    }),
                    this.publishPersonPropertyEvents(precalculatedPersonProperties).catch((error) => {
                        throw new Error(`Failed to publish person property events: ${error.message}`)
                    }),
                ])

                return { backgroundTask }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', `Stopping ${this.name}...`)
        await this.eventKafkaConsumer.disconnect()

        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', `${this.name} stopped!`)
    }

    public isHealthy(): HealthCheckResult {
        return this.eventKafkaConsumer.isHealthy()
    }
}
