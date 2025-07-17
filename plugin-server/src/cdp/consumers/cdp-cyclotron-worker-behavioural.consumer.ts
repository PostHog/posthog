import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { convertToHogFunctionInvocationGlobals } from '../../cdp/utils'
import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { HogFunctionInvocationGlobals } from '../types'
import { execHog } from '../utils/hog-exec'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase } from './cdp-base.consumer'

export const counterParseError = new Counter({
    name: 'cdp_behavioural_function_parse_error',
    help: 'A behavioural function invocation was parsed with an error',
    labelNames: ['error'],
})

export const counterEventsConsumed = new Counter({
    name: 'cdp_behavioural_events_consumed_total',
    help: 'Total number of events consumed by the behavioural consumer',
})

export const counterEventsMatchedTotal = new Counter({
    name: 'cdp_behavioural_events_matched_total',
    help: 'Total number of events that matched at least one action filter',
})

export class CdpCyclotronWorkerBehaviouralConsumer extends CdpConsumerBase {
    protected name = 'CdpCyclotronWorkerBehaviouralConsumer'
    protected kafkaConsumer: KafkaConsumer

    constructor(
        hub: Hub,
        topic: string = KAFKA_EVENTS_JSON,
        groupId: string = 'cdp-cyclotron-worker-behavioural-consumer'
    ) {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
    }

    public async processBatch(invocationGlobals: HogFunctionInvocationGlobals[]): Promise<void> {
        return await this.runInstrumented('processBatch', async () => {
            if (!invocationGlobals.length) {
                return
            }

            // Track events consumed and matched (absolute numbers)
            let eventsMatched = 0

            for (const event of invocationGlobals) {
                const matched = await this.processEvent(event)
                if (matched) {
                    eventsMatched++
                }
            }

            // Update metrics with absolute numbers
            counterEventsConsumed.inc(invocationGlobals.length)
            counterEventsMatchedTotal.inc(eventsMatched)
        })
    }

    private async processEvent(event: HogFunctionInvocationGlobals): Promise<boolean> {
        try {
            const teamId = event.project.id
            const actions = await this.loadActionsForTeam(teamId)

            if (!actions.length) {
                logger.debug('No actions found for team', { teamId })
                return false
            }

            let eventMatched = false
            for (const action of actions) {
                const matched = await this.doesEventMatchAction(event, action)
                if (matched) {
                    eventMatched = true
                }
            }

            return eventMatched
        } catch (error) {
            logger.error('Error processing event', {
                teamId: event.project.id,
                eventName: event.event.event,
                error,
            })
            return false
        }
    }

    private async loadActionsForTeam(teamId: number): Promise<Array<{ id: string; name: string; bytecode: any }>> {
        try {
            const actions = await this.hub.actionManagerCDP.getActionsForTeam(teamId)
            return actions.map((action) => ({
                id: String(action.id),
                name: action.name,
                bytecode: action.bytecode,
            }))
        } catch (error) {
            logger.error('Error loading actions for team', { teamId, error })
            return []
        }
    }

    private async doesEventMatchAction(
        event: HogFunctionInvocationGlobals,
        action: { id: string; name: string; bytecode: any }
    ): Promise<boolean> {
        if (!action.bytecode) {
            return false
        }

        try {
            // Convert event to filter globals format
            const filterGlobals = convertToHogFunctionFilterGlobal(event)

            // Execute bytecode directly
            const execHogOutcome = await execHog(action.bytecode, {
                globals: filterGlobals,
                telemetry: false,
            })

            if (!execHogOutcome.execResult || execHogOutcome.error || execHogOutcome.execResult.error) {
                throw execHogOutcome.error ?? execHogOutcome.execResult?.error ?? new Error('Unknown error')
            }

            const matchedFilter =
                typeof execHogOutcome.execResult.result === 'boolean' && execHogOutcome.execResult.result

            return matchedFilter
        } catch (error) {
            logger.error('Error executing action bytecode', {
                actionId: action.id,
                teamId: event.project.id,
                error,
            })
            return false
        }
    }

    // This consumer always parses from kafka
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        return await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpBehaviouralConsumer.handleEachBatch.parseKafkaMessages`,
                func: async () => {
                    const events: HogFunctionInvocationGlobals[] = []

                    await Promise.all(
                        messages.map(async (message) => {
                            try {
                                const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                                const team = await this.hub.teamManager.getTeam(clickHouseEvent.team_id)

                                if (!team) {
                                    return
                                }
                                events.push(
                                    convertToHogFunctionInvocationGlobals(clickHouseEvent, team, this.hub.SITE_URL)
                                )
                            } catch (e) {
                                logger.error('Error parsing message', e)
                                counterParseError.labels({ error: e.message }).inc()
                            }
                        })
                    )
                    return events
                },
            })
        )
    }

    public async start(): Promise<void> {
        await super.start()
        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await this.runInstrumented('handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                await this.processBatch(invocationGlobals)

                return { backgroundTask: Promise.resolve() }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping behavioural consumer...')
        await this.kafkaConsumer.disconnect()
        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Behavioural consumer stopped!')
    }

    public isHealthy() {
        return this.kafkaConsumer.isHealthy()
    }
}
