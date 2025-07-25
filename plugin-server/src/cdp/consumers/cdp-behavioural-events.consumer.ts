import { Client as CassandraClient } from 'cassandra-driver'
import { createHash } from 'crypto'
import { Message } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, RawClickHouseEvent } from '../../types'
import { Action } from '../../utils/action-manager-cdp'
import { BehavioralCounterRepository, CounterUpdate } from '../../utils/db/cassandra/behavioural-counter.repository'
import {
    OccurrenceUpdate,
    PersonEventOccurrenceRepository,
} from '../../utils/db/cassandra/person-event-occurrence.repository'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { HogFunctionFilterGlobals } from '../types'
import { execHog } from '../utils/hog-exec'
import { convertClickhouseRawEventToFilterGlobals } from '../utils/hog-function-filtering'
import { getHogWorkerPool } from '../utils/hog-worker-pool'
import { CdpConsumerBase } from './cdp-base.consumer'

export type BehavioralEvent = {
    teamId: number
    filterGlobals: HogFunctionFilterGlobals
    personId: string
}

export const counterParseError = new Counter({
    name: 'cdp_behavioural_function_parse_error',
    help: 'A behavioural function invocation was parsed with an error',
    labelNames: ['error'],
})

export const counterEventsDropped = new Counter({
    name: 'cdp_behavioural_events_dropped_total',
    help: 'Total number of events dropped due to missing personId or other validation errors',
    labelNames: ['reason'],
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
    protected cassandra: CassandraClient | null
    protected behavioralCounterRepository: BehavioralCounterRepository | null
    protected personEventOccurrenceRepository: PersonEventOccurrenceRepository | null
    private filterHashCache = new Map<string, string>()

    constructor(hub: Hub, topic: string = KAFKA_EVENTS_JSON, groupId: string = 'cdp-behavioural-events-consumer') {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })

        // Only initialize Cassandra client if the feature is enabled
        if (hub.WRITE_BEHAVIOURAL_COUNTERS_TO_CASSANDRA) {
            this.cassandra = new CassandraClient({
                contactPoints: [hub.CASSANDRA_HOST],
                localDataCenter: 'datacenter1',
                keyspace: hub.CASSANDRA_KEYSPACE,
                credentials:
                    hub.CASSANDRA_USER && hub.CASSANDRA_PASSWORD
                        ? { username: hub.CASSANDRA_USER, password: hub.CASSANDRA_PASSWORD }
                        : undefined,
            })
            this.behavioralCounterRepository = new BehavioralCounterRepository(this.cassandra)
            this.personEventOccurrenceRepository = new PersonEventOccurrenceRepository(this.cassandra)
        } else {
            this.cassandra = null
            this.behavioralCounterRepository = null
            this.personEventOccurrenceRepository = null
        }
    }

    public async processBatch(events: BehavioralEvent[]): Promise<void> {
        return await this.runInstrumented('processBatch', async () => {
            if (!events.length) {
                return
            }

            // Track events consumed and matched (absolute numbers)
            let eventsMatched = 0
            const counterUpdates: CounterUpdate[] = []
            const occurrenceUpdates: OccurrenceUpdate[] = []

            const results = await Promise.all(events.map((event) => this.processEvent(event, counterUpdates)))
            eventsMatched = results.reduce((sum, count) => sum + count, 0)

            // Prepare occurrence updates for all events, deduplicating within the batch
            const occurrenceSet = new Set<string>()
            events.forEach((event) => {
                const key = `${event.teamId}:${event.personId}:${event.filterGlobals.event}`
                if (!occurrenceSet.has(key)) {
                    occurrenceSet.add(key)
                    occurrenceUpdates.push({
                        teamId: event.teamId,
                        personId: event.personId,
                        eventName: event.filterGlobals.event,
                    })
                }
            })

            // Batch write all updates in parallel
            const writePromises = []
            if (counterUpdates.length > 0 && this.hub.WRITE_BEHAVIOURAL_COUNTERS_TO_CASSANDRA && this.cassandra) {
                writePromises.push(this.writeBehavioralCounters(counterUpdates))
            }
            if (occurrenceUpdates.length > 0 && this.hub.WRITE_BEHAVIOURAL_COUNTERS_TO_CASSANDRA && this.cassandra) {
                writePromises.push(this.writePersonEventOccurrences(occurrenceUpdates))
            }

            if (writePromises.length > 0) {
                await Promise.all(writePromises)
            }

            // Update metrics with absolute numbers
            counterEventsConsumed.inc(events.length)
            counterEventsMatchedTotal.inc(eventsMatched)
        })
    }

    private async processEvent(event: BehavioralEvent, counterUpdates: CounterUpdate[]): Promise<number> {
        try {
            const actions = await this.loadActionsForTeam(event.teamId)

            if (!actions.length) {
                logger.debug('No actions found for team', { teamId: event.teamId })
                return 0
            }

            const results = await Promise.all(
                actions.map((action) => this.doesEventMatchAction(event, action, counterUpdates))
            )

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

    private async doesEventMatchAction(
        event: BehavioralEvent,
        action: Action,
        counterUpdates: CounterUpdate[]
    ): Promise<boolean> {
        if (!action.bytecode) {
            return false
        }

        try {
            // Choose execution method based on feature flag
            let execHogOutcome
            if (this.hub.USE_HOG_WORKER_THREADS) {
                // Execute in worker thread for better performance
                const workerPool = getHogWorkerPool()
                execHogOutcome = await workerPool.execute({
                    bytecode: action.bytecode,
                    globals: event.filterGlobals,
                    timeout: 100, // Shorter timeout for filters
                    telemetry: false,
                })
            } else {
                // Execute in main thread (fallback)
                execHogOutcome = await execHog(action.bytecode, {
                    globals: event.filterGlobals,
                    telemetry: false,
                })
            }

            // Handle different return formats based on execution method
            let matchedFilter: boolean
            if (this.hub.USE_HOG_WORKER_THREADS) {
                // Worker thread returns the result directly
                matchedFilter = typeof execHogOutcome === 'boolean' && execHogOutcome
            } else {
                // Direct execution returns the wrapped result
                if (!execHogOutcome.execResult || execHogOutcome.error || execHogOutcome.execResult.error) {
                    throw execHogOutcome.error ?? execHogOutcome.execResult?.error ?? new Error('Unknown error')
                }
                matchedFilter =
                    typeof execHogOutcome.execResult.result === 'boolean' && execHogOutcome.execResult.result
            }

            if (matchedFilter) {
                const filterHash = this.createFilterHash(action.bytecode!)
                const date = new Date().toISOString().split('T')[0]
                counterUpdates.push({
                    teamId: event.teamId,
                    filterHash,
                    personId: event.personId,
                    date,
                })
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

    private async writeBehavioralCounters(updates: CounterUpdate[]): Promise<void> {
        if (!this.behavioralCounterRepository) {
            logger.warn('Behavioral counter repository not initialized, skipping counter writes')
            return
        }

        try {
            await this.behavioralCounterRepository.batchIncrementCounters(updates)
        } catch (error) {
            logger.error('Error batch writing behavioral counters', { error, updateCount: updates.length })
        }
    }

    private async writePersonEventOccurrences(updates: OccurrenceUpdate[]): Promise<void> {
        if (!this.personEventOccurrenceRepository) {
            logger.warn('Person event occurrence repository not initialized, skipping occurrence writes')
            return
        }

        try {
            await this.personEventOccurrenceRepository.batchInsertOccurrences(updates)
        } catch (error) {
            logger.error('Error batch writing person event occurrences', { error, updateCount: updates.length })
        }
    }

    private createFilterHash(bytecode: any): string {
        const data = typeof bytecode === 'string' ? bytecode : JSON.stringify(bytecode)

        // Check cache first
        if (this.filterHashCache.has(data)) {
            return this.filterHashCache.get(data)!
        }

        // Calculate hash and cache it
        const hash = createHash('sha256').update(data).digest('hex').substring(0, 16)
        this.filterHashCache.set(data, hash)
        return hash
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

                            if (!clickHouseEvent.person_id) {
                                logger.error('Dropping event: missing person_id', {
                                    teamId: clickHouseEvent.team_id,
                                    event: clickHouseEvent.event,
                                    uuid: clickHouseEvent.uuid,
                                })
                                counterEventsDropped.labels({ reason: 'missing_person_id' }).inc()
                                return
                            }

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

        // Only connect to Cassandra if initialized
        if (this.cassandra) {
            logger.info('🤔', `Connecting to Cassandra...`)
            await this.cassandra.connect()
            logger.info('👍', `Cassandra ready`)
        } else {
            logger.info('ℹ️', `Cassandra disabled, skipping connection`)
        }

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

        // Only shutdown Cassandra if it was initialized
        if (this.cassandra) {
            await this.cassandra.shutdown()
        }

        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Behavioural events consumer stopped!')
    }

    public isHealthy() {
        return this.kafkaConsumer.isHealthy()
    }
}
