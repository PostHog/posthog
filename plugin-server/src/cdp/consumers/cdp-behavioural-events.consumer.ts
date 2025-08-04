import { auth, Client as CassandraClient } from 'cassandra-driver'
import { createHash } from 'crypto'
import { Message } from 'node-rdkafka'
import { join } from 'path'
import Piscina from 'piscina'
import { Counter, Histogram } from 'prom-client'

import { isCloud } from '~/utils/env-utils'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, RawClickHouseEvent } from '../../types'
import { Action } from '../../utils/action-manager-cdp'
import { BehavioralCounterRepository, CounterUpdate } from '../../utils/db/cassandra/behavioural-counter.repository'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { HogFunctionFilterGlobals } from '../types'
import { convertClickhouseRawEventToFilterGlobals } from '../utils/hog-function-filtering'
import { CdpConsumerBase } from './cdp-base.consumer'

export type BehavioralEvent = {
    teamId: number
    filterGlobals: HogFunctionFilterGlobals
    personId: string
}

export const histogramWorkerPoolExecution = new Histogram({
    name: 'cdp_behavioural_worker_pool_execution_duration_ms',
    help: 'Time spent executing bytecode in worker pool',
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
})

export const histogramActionLoading = new Histogram({
    name: 'cdp_behavioural_action_loading_duration_ms',
    help: 'Time spent loading actions for teams',
    buckets: [1, 5, 10, 25, 50, 100, 250, 500],
})

export const counterWorkerPoolTasks = new Counter({
    name: 'cdp_behavioural_worker_pool_tasks_total',
    help: 'Total number of tasks submitted to worker pool',
    labelNames: ['status'],
})

export const histogramBatchProcessingSteps = new Histogram({
    name: 'cdp_behavioural_batch_processing_steps_duration_ms',
    help: 'Time spent in different batch processing steps',
    labelNames: ['step'],
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
})

export const histogramActionsPerTeam = new Histogram({
    name: 'cdp_behavioural_actions_per_team',
    help: 'Number of actions loaded per team',
    buckets: [0, 1, 2, 5, 10, 20, 50, 100, 200, 500],
})

export class CdpBehaviouralEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpBehaviouralEventsConsumer'
    protected kafkaConsumer: KafkaConsumer
    protected cassandra: CassandraClient | null
    protected behavioralCounterRepository: BehavioralCounterRepository | null
    private filterHashCache = new Map<string, string>()
    private workerPool: Piscina

    constructor(hub: Hub, topic: string = KAFKA_EVENTS_JSON, groupId: string = 'cdp-behavioural-events-consumer') {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })

        // Initialize Piscina worker pool for parallel HOG execution
        this.workerPool = new Piscina({
            filename: join(__dirname, '../workers/hog-executor.worker.js'),
            maxThreads: Math.max(2, Math.floor(require('os').cpus().length * 0.5)),
            minThreads: 2,
            resourceLimits: {
                maxOldGenerationSizeMb: 256,
                maxYoungGenerationSizeMb: 64,
            },
        })

        // Only initialize Cassandra client if the feature is enabled
        if (hub.WRITE_BEHAVIOURAL_COUNTERS_TO_CASSANDRA) {
            this.cassandra = new CassandraClient({
                contactPoints: [hub.CASSANDRA_HOST],
                protocolOptions: {
                    port: hub.CASSANDRA_PORT,
                },
                sslOptions: isCloud()
                    ? {
                          rejectUnauthorized: true,
                      }
                    : undefined,
                localDataCenter: hub.CASSANDRA_LOCAL_DATACENTER,
                keyspace: hub.CASSANDRA_KEYSPACE,
                authProvider: new auth.PlainTextAuthProvider(
                    hub.CASSANDRA_USER || 'cassandra',
                    hub.CASSANDRA_PASSWORD || 'cassandra'
                ),
            })
            this.behavioralCounterRepository = new BehavioralCounterRepository(this.cassandra)
        } else {
            this.cassandra = null
            this.behavioralCounterRepository = null
        }
    }

    public async processBatch(events: BehavioralEvent[]): Promise<void> {
        return await this.runInstrumented('processBatch', async () => {
            if (!events.length) {
                return
            }

            const counterUpdates: CounterUpdate[] = []

            // Time event processing
            const eventProcessingTimer = histogramBatchProcessingSteps.labels({ step: 'event_processing' }).startTimer()
            await Promise.all(events.map((event) => this.processEvent(event, counterUpdates)))
            eventProcessingTimer()

            // Time Cassandra writes
            if (counterUpdates.length > 0 && this.hub.WRITE_BEHAVIOURAL_COUNTERS_TO_CASSANDRA && this.cassandra) {
                const cassandraTimer = histogramBatchProcessingSteps.labels({ step: 'cassandra_write' }).startTimer()
                await this.writeBehavioralCounters(counterUpdates)
                cassandraTimer()
            }
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
        const timer = histogramActionLoading.startTimer()
        try {
            const actions = await this.hub.actionManagerCDP.getActionsForTeam(teamId)
            timer()
            histogramActionsPerTeam.observe(actions.length)
            return actions
        } catch (error) {
            timer()
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
            // Execute bytecode in worker thread for better performance
            const workerTimer = histogramWorkerPoolExecution.startTimer()
            counterWorkerPoolTasks.labels({ status: 'submitted' }).inc()

            const result = await this.workerPool.run({
                bytecode: action.bytecode,
                filterGlobals: event.filterGlobals,
            })

            workerTimer()

            if (result.error) {
                counterWorkerPoolTasks.labels({ status: 'error' }).inc()
                throw result.error
            }

            counterWorkerPoolTasks.labels({ status: 'success' }).inc()

            if (result.matched) {
                const filterHash = this.createFilterHash(action.bytecode!)
                const date = new Date().toISOString().split('T')[0]
                counterUpdates.push({
                    teamId: event.teamId,
                    filterHash,
                    personId: event.personId,
                    date,
                })
            }

            return result.matched
        } catch (error) {
            logger.error('Error executing action bytecode in worker', {
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

        // Shutdown worker pool
        await this.workerPool.destroy()

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
