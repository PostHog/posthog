import { types as CassandraTypes } from 'cassandra-driver'
import { createHash } from 'crypto'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, RawClickHouseEvent } from '../../types'
import { Action } from '../../utils/action-manager-cdp'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { HogFunctionFilterGlobals } from '../types'
import { execHog } from '../utils/hog-exec'
import { convertClickhouseRawEventToFilterGlobals } from '../utils/hog-function-filtering'
import { CdpConsumerBase } from './cdp-base.consumer'

export type BehavioralEvent = {
    teamId: number
    filterGlobals: HogFunctionFilterGlobals
    personId?: string
}

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

export class CdpBehaviouralEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpBehaviouralEventsConsumer'
    protected kafkaConsumer: KafkaConsumer

    constructor(hub: Hub, topic: string = KAFKA_EVENTS_JSON, groupId: string = 'cdp-behavioural-events-consumer') {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
    }

    public async processBatch(events: BehavioralEvent[]): Promise<void> {
        return await this.runInstrumented('processBatch', async () => {
            if (!events.length) {
                return
            }

            // Track events consumed and matched (absolute numbers)
            let eventsMatched = 0

            const results = await Promise.all(events.map((event) => this.processEvent(event)))
            eventsMatched = results.reduce((sum, count) => sum + count, 0)

            // Update metrics with absolute numbers
            counterEventsConsumed.inc(events.length)
            counterEventsMatchedTotal.inc(eventsMatched)
        })
    }

    private async processEvent(event: BehavioralEvent): Promise<number> {
        try {
            const actions = await this.loadActionsForTeam(event.teamId)

            if (!actions.length) {
                logger.debug('No actions found for team', { teamId: event.teamId })
                return 0
            }

            const results = await Promise.all(actions.map((action) => this.doesEventMatchAction(event, action)))

            return results.filter(Boolean).length
        } catch (error) {
            logger.error('Error processing event', {
                eventName: event.filterGlobals.event,
                error,
            })
            return 0
        }
    }

    private async loadActionsForTeam(teamId: number): Promise<Action[]> {
        try {
            const actions = await this.hub.actionManagerCDP.getActionsForTeam(teamId)
            return actions
        } catch (error) {
            logger.error('Error loading actions for team', { teamId, error })
            return []
        }
    }

    private async doesEventMatchAction(event: BehavioralEvent, action: Action): Promise<boolean> {
        if (!action.bytecode) {
            return false
        }

        try {
            // Execute bytecode directly with the filter globals
            const execHogOutcome = await execHog(action.bytecode, {
                globals: event.filterGlobals,
                telemetry: false,
            })

            if (!execHogOutcome.execResult || execHogOutcome.error || execHogOutcome.execResult.error) {
                throw execHogOutcome.error ?? execHogOutcome.execResult?.error ?? new Error('Unknown error')
            }

            const matchedFilter =
                typeof execHogOutcome.execResult.result === 'boolean' && execHogOutcome.execResult.result

            // If matched and we have person info, write to Cassandra
            if (matchedFilter && event.personId) {
                await this.writeBehavioralCounter(event.teamId, action, event.personId)
            }

            return matchedFilter
        } catch (error) {
            logger.error('Error executing action bytecode', {
                actionId: String(action.id),
                error,
            })
            return false
        }
    }

    private async writeBehavioralCounter(teamId: number, action: Action, personId: string): Promise<void> {
        try {
            // Create filter hash from action bytecode
            const filterHash = this.createFilterHash(action.bytecode!)

            // Get current date in YYYY-MM-DD format
            const date = new Date().toISOString().split('T')[0]

            // Update counter in Cassandra
            await this.hub.cassandra.execute(
                'UPDATE behavioral_event_counters SET count = count + 1 WHERE team_id = ? AND filter_hash = ? AND person_id = ? AND date = ?',
                [teamId, filterHash, CassandraTypes.Uuid.fromString(personId), date],
                { prepare: true }
            )
        } catch (error) {
            logger.error('Error writing behavioral counter', {
                teamId,
                actionId: action.id,
                personId,
                error,
            })
        }
    }

    private createFilterHash(bytecode: any): string {
        const data = typeof bytecode === 'string' ? bytecode : JSON.stringify(bytecode)
        return createHash('sha256').update(data).digest('hex').substring(0, 16)
    }

    // This consumer always parses from kafka
    public async _parseKafkaBatch(messages: Message[]): Promise<BehavioralEvent[]> {
        return await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpBehaviouralEventsConsumer.handleEachBatch.parseKafkaMessages`,
                func: () => {
                    const events: BehavioralEvent[] = []

                    messages.forEach((message) => {
                        try {
                            const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                            // Convert directly to filter globals
                            const filterGlobals = convertClickhouseRawEventToFilterGlobals(clickHouseEvent)

                            events.push({
                                teamId: clickHouseEvent.team_id,
                                filterGlobals,
                                personId: clickHouseEvent.person_id,
                            })
                        } catch (e) {
                            logger.error('Error parsing message', e)
                            counterParseError.labels({ error: e.message }).inc()
                        }
                    })
                    // Return Promise.resolve to satisfy runInstrumentedFunction's Promise return type
                    // without needing async/await since all operations are synchronous
                    return Promise.resolve(events)
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
                const events = await this._parseKafkaBatch(messages)
                await this.processBatch(events)

                return { backgroundTask: Promise.resolve() }
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

    public isHealthy() {
        return this.kafkaConsumer.isHealthy()
    }
}
