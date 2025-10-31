import { Message } from 'node-rdkafka'
import { Histogram } from 'prom-client'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { Action, ActionManagerCDP } from '~/utils/action-manager-cdp'

import { KAFKA_CDP_CLICKHOUSE_PREFILTERED_EVENTS, KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { HogFunctionFilterGlobals } from '../types'
import { execHog } from '../utils/hog-exec'
import { convertClickhouseRawEventToFilterGlobals } from '../utils/hog-function-filtering'
import { CdpConsumerBase } from './cdp-base.consumer'

export type PreCalculatedEvent = {
    uuid: string // event uuid
    team_id: number
    evaluation_timestamp: string
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
    name: 'cdp_behavioural_batch_processing_steps_duration_ms',
    help: 'Time spent in different batch processing steps',
    labelNames: ['step'],
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
})

export class CdpBehaviouralEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpBehaviouralEventsConsumer'
    private kafkaConsumer: KafkaConsumer
    private actionManager: ActionManagerCDP

    constructor(hub: Hub, topic: string = KAFKA_EVENTS_JSON, groupId: string = 'cdp-behavioural-events-consumer') {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
        this.actionManager = new ActionManagerCDP(hub.db.postgres)
    }

    @instrumented('cdpBehaviouralEventsConsumer.publishEvents')
    private async publishEvents(events: ProducedEvent[]): Promise<void> {
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
            logger.error('Error publishing events', {
                error,
                queueLength: events.length,
            })
            // Don't clear queue on error - messages will be retried with next batch
        }
    }

    // Evaluate if event matches action using bytecode execution
    private async evaluateEventAgainstAction(
        filterGlobals: HogFunctionFilterGlobals,
        action: Action
    ): Promise<boolean> {
        if (!action.bytecode) {
            return false
        }

        try {
            const { execResult } = await execHog(action.bytecode, {
                globals: filterGlobals,
            })

            return execResult?.result ?? false
        } catch (error) {
            logger.error('Error executing action bytecode', {
                actionId: action.id,
                error,
            })
            return false
        }
    }

    // This consumer always parses from kafka and creates events directly
    @instrumented('cdpBehaviouralEventsConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<ProducedEvent[]> {
        return await this.runWithHeartbeat(async () => {
            const events: ProducedEvent[] = []

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

            // Step 2: Fetch all actions for all teams in one query
            const teamIds = Array.from(eventsByTeam.keys())
            const actionsByTeam = await this.actionManager.getActionsForTeams(teamIds)

            // Step 3: Process each team's events with their actions
            for (const [teamId, teamEvents] of Array.from(eventsByTeam.entries())) {
                try {
                    const actions = actionsByTeam[String(teamId)] || []

                    if (actions.length === 0) {
                        // Skip teams with no actions
                        continue
                    }

                    // Process each event for this team
                    for (const clickHouseEvent of teamEvents) {
                        // Convert timestamp to ClickHouse DateTime64(6) format
                        // Input: '2025-03-03T10:15:46.319000-08:00' -> Output: '2025-03-03 10:15:46.319000'
                        const evaluationTimestamp = new Date(clickHouseEvent.timestamp)
                            .toISOString()
                            .replace('T', ' ')
                            .replace('Z', '')

                        // Convert to filter globals for action evaluation
                        const filterGlobals = convertClickhouseRawEventToFilterGlobals(clickHouseEvent)

                        // Evaluate event against each action for this team
                        for (const action of actions) {
                            const matches = await this.evaluateEventAgainstAction(filterGlobals, action)

                            // Only publish if event matches the action (don't publish non-matches)
                            if (matches) {
                                // Hash the action bytecode/id as the condition identifier
                                // This ensures consistent condition hashes for the same action

                                const preCalculatedEvent: ProducedEvent = {
                                    key: filterGlobals.distinct_id,
                                    payload: {
                                        uuid: filterGlobals.uuid,
                                        team_id: clickHouseEvent.team_id,
                                        evaluation_timestamp: evaluationTimestamp,
                                        person_id: clickHouseEvent.person_id!,
                                        distinct_id: filterGlobals.distinct_id,
                                        condition: String(action.id),
                                        source: `action_${action.id}`,
                                    },
                                }

                                events.push(preCalculatedEvent)
                            }
                        }
                    }
                } catch (e) {
                    logger.error('Error processing team events', { teamId, error: e })
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
                    throw new Error(`Failed to publish behavioural events: ${error.message}`)
                })

                return { backgroundTask }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping behavioural events consumer...')
        await this.kafkaConsumer.disconnect()

        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Behavioural events consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
