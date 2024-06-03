import { features, KafkaConsumer, librdkafkaVersion, Message } from 'node-rdkafka'
import { Counter, Gauge, Histogram } from 'prom-client'

import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars, createRdProducerConfigFromEnvVars } from '../../kafka/config'
import { createKafkaProducer } from '../../kafka/producer'
import { addSentryBreadcrumbsEventListeners } from '../../main/ingestion-queues/kafka-metrics'
import { runInstrumentedFunction } from '../../main/utils'
import { GroupTypeToColumnIndex, PluginsServerConfig, RawClickHouseEvent, RedisPool, TeamId } from '../../types'
import { KafkaProducerWrapper } from '../../utils/db/kafka-producer-wrapper'
import { PostgresRouter } from '../../utils/db/postgres'
// import {
//     allSettledWithConcurrency,
//     bufferFileDir,
//     getPartitionsForTopic,
//     now,
//     parseKafkaBatch,
//     queryWatermarkOffsets,
// } from './utils'
import { convertToPostIngestionEvent } from '../../utils/event'
import { status } from '../../utils/status'
import { createRedisPool } from '../../utils/utils'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { OrganizationManager } from '../../worker/ingestion/organization-manager'
import { TeamManager } from '../../worker/ingestion/team-manager'
import { HogExecutor } from './hog-executor'
import { HogFunctionManager } from './hog-function-manager'
import { HogFunctionInvocation } from './types'
import { convertToHogFunctionInvocationContext } from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// WARNING: Do not change this - it will essentially reset the consumer
const KAFKA_CONSUMER_GROUP_ID = 'cdp-function-executor'
const KAFKA_CONSUMER_GROUP_ID_OVERFLOW = 'cdp-function-executor-overflow'
const KAFKA_CONSUMER_SESSION_TIMEOUT_MS = 90_000
const CAPTURE_OVERFLOW_REDIS_KEY = '@posthog/capture-overflow/cdp-function-executor'
const BUCKETS_KB_WRITTEN = [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity]

const histogramKafkaBatchSize = new Histogram({
    name: 'cdp_function_executor_batch_size',
    help: 'The size of the batches we are receiving from Kafka',
    buckets: [0, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000, Infinity],
})

const histogramKafkaBatchSizeKb = new Histogram({
    name: 'cdp_function_executor_batch_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: BUCKETS_KB_WRITTEN,
})

export interface TeamIDWithConfig {
    teamId: TeamId | null
    consoleLogIngestionEnabled: boolean
}

export class CdpProcessedEventsConsumer {
    redisPool: RedisPool
    // overflowDetection?: OverflowManager
    batchConsumer?: BatchConsumer
    teamManager: TeamManager
    organizationManager: OrganizationManager
    groupTypeManager: GroupTypeManager
    hogFunctionManager: HogFunctionManager
    hogExecutor: HogExecutor
    topic: string
    consumerGroupId: string
    isStopping = false

    private kafkaProducer?: KafkaProducerWrapper

    private promises: Set<Promise<any>> = new Set()

    constructor(
        private config: PluginsServerConfig,
        private postgres: PostgresRouter,
        private consumeOverflow: boolean
    ) {
        // TODO: Add overflow topic
        this.topic = consumeOverflow ? KAFKA_EVENTS_JSON : KAFKA_EVENTS_JSON
        this.consumerGroupId = this.consumeOverflow ? KAFKA_CONSUMER_GROUP_ID_OVERFLOW : KAFKA_CONSUMER_GROUP_ID

        // NOTE: globalServerConfig contains the default pluginServer values, typically not pointing at dedicated resources like kafka or redis
        // We still connect to some of the non-dedicated resources such as postgres or the Replay events kafka.
        this.redisPool = createRedisPool(this.config)

        // if (globalServerConfig.SESSION_RECORDING_OVERFLOW_ENABLED && captureRedis && !consumeOverflow) {
        //     this.overflowDetection = new OverflowManager(
        //         globalServerConfig.SESSION_RECORDING_OVERFLOW_BUCKET_CAPACITY,
        //         globalServerConfig.SESSION_RECORDING_OVERFLOW_BUCKET_REPLENISH_RATE,
        //         globalServerConfig.SESSION_RECORDING_OVERFLOW_MIN_PER_BATCH,
        //         24 * 3600, // One day,
        //         CAPTURE_OVERFLOW_REDIS_KEY,
        //         captureRedis
        //     )
        // }

        this.teamManager = new TeamManager(postgres, config)
        this.organizationManager = new OrganizationManager(postgres, this.teamManager)
        this.groupTypeManager = new GroupTypeManager(postgres, this.teamManager)
        this.hogFunctionManager = new HogFunctionManager(postgres, config)
        this.hogExecutor = new HogExecutor(this.hogFunctionManager)
    }

    private get connectedBatchConsumer(): KafkaConsumer | undefined {
        // Helper to only use the batch consumer if we are actually connected to it - otherwise it will throw errors
        const consumer = this.batchConsumer?.consumer
        return consumer && consumer.isConnected() ? consumer : undefined
    }

    private scheduleWork<T>(promise: Promise<T>): Promise<T> {
        this.promises.add(promise)
        void promise.finally(() => this.promises.delete(promise))
        return promise
    }

    public async consume(invocation: HogFunctionInvocation): Promise<void> {
        console.log('INVOKING')

        await this.hogExecutor.executeMatchingFunctions(invocation)
    }

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        status.info('🔁', `cdp-function-executor - handling batch`, {
            size: messages.length,
        })
        await runInstrumentedFunction({
            statsKey: `cdpFunctionExecutor.handleEachBatch`,
            sendTimeoutGuardToSentry: false,
            func: async () => {
                histogramKafkaBatchSize.observe(messages.length)
                histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

                const invocations: HogFunctionInvocation[] = []

                await runInstrumentedFunction({
                    statsKey: `cdpFunctionExecutor.handleEachBatch.parseKafkaMessages`,
                    func: async () => {
                        // TODO: Early exit for events without associated hooks

                        await Promise.all(
                            messages.map(async (message) => {
                                try {
                                    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent

                                    let groupTypes: GroupTypeToColumnIndex | undefined = undefined

                                    if (
                                        await this.organizationManager.hasAvailableFeature(
                                            clickHouseEvent.team_id,
                                            'group_analytics'
                                        )
                                    ) {
                                        // If the organization has group analytics enabled then we enrich the event with group data
                                        groupTypes = await this.groupTypeManager.fetchGroupTypes(
                                            clickHouseEvent.team_id
                                        )
                                    }

                                    // TODO: Clean up all of this and parallelise
                                    // TODO: We can fetch alot of teams and things in parallel

                                    const team = await this.teamManager.fetchTeam(clickHouseEvent.team_id)
                                    if (!team) {
                                        return
                                    }
                                    const context = convertToHogFunctionInvocationContext(
                                        clickHouseEvent,
                                        team,
                                        this.config.SITE_URL ?? 'http://localhost:8000',
                                        groupTypes
                                    )

                                    invocations.push({
                                        team,
                                        context,
                                    })
                                } catch (e) {
                                    status.error('Error parsing message', e)
                                }
                            })
                        )
                    },
                })
                heartbeat()

                await runInstrumentedFunction({
                    statsKey: `cdpFunctionExecutor.handleEachBatch.consumeBatch`,
                    func: async () => {
                        // TODO: Parallelise this
                        for (const message of invocations) {
                            await this.consume(message)
                            heartbeat()
                        }
                    },
                })
            },
        })
    }

    public async start(): Promise<void> {
        status.info('🔁', 'cdp-function-executor - starting', {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        // NOTE: This is the only place where we need to use the shared server config
        const globalConnectionConfig = createRdConnectionConfigFromEnvVars(this.config)
        const globalProducerConfig = createRdProducerConfigFromEnvVars(this.config)

        this.kafkaProducer = new KafkaProducerWrapper(
            await createKafkaProducer(globalConnectionConfig, globalProducerConfig)
        )

        this.kafkaProducer.producer.connect()

        // Create a node-rdkafka consumer that fetches batches of messages, runs
        // eachBatchWithContext, then commits offsets for the batch.
        // the batch consumer reads from the session replay kafka cluster
        this.batchConsumer = await startBatchConsumer({
            connectionConfig: createRdConnectionConfigFromEnvVars(this.config),
            groupId: this.consumerGroupId,
            topic: this.topic,
            autoCommit: true,
            sessionTimeout: KAFKA_CONSUMER_SESSION_TIMEOUT_MS,
            maxPollIntervalMs: this.config.KAFKA_CONSUMPTION_MAX_POLL_INTERVAL_MS,
            // the largest size of a message that can be fetched by the consumer.
            // the largest size our MSK cluster allows is 20MB
            // we only use 9 or 10MB but there's no reason to limit this 🤷️
            consumerMaxBytes: this.config.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.config.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            // our messages are very big, so we don't want to buffer too many
            // queuedMinMessages: this.config.SESSION_RECORDING_KAFKA_QUEUE_SIZE,
            consumerMaxWaitMs: this.config.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            consumerErrorBackoffMs: this.config.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            fetchBatchSize: this.config.INGESTION_BATCH_SIZE,
            batchingTimeoutMs: this.config.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            topicCreationTimeoutMs: this.config.KAFKA_TOPIC_CREATION_TIMEOUT_MS,
            eachBatch: async (messages, { heartbeat }) => {
                return await this.scheduleWork(this.handleEachBatch(messages, heartbeat))
            },
            callEachBatchWhenEmpty: true, // Useful as we will still want to account for flushing sessions
            debug: this.config.SESSION_RECORDING_KAFKA_DEBUG,
        })

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            status.info('🔁', 'cdp-function-executor batch consumer disconnected, cleaning up', { err })
            await this.stop()
        })
    }

    public async stop(): Promise<PromiseSettledResult<any>[]> {
        status.info('🔁', 'cdp-function-executor - stopping')
        this.isStopping = true

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        await this.batchConsumer?.stop()

        const promiseResults = await Promise.allSettled(this.promises)

        await this.kafkaProducer?.disconnect()
        // Finally we clear up redis once we are sure everything else has been handled
        await this.redisPool.drain()
        await this.redisPool.clear()

        status.info('👍', 'cdp-function-executor - stopped!')

        return promiseResults
    }

    public isHealthy() {
        // TODO: Maybe extend this to check if we are shutting down so we don't get killed early.
        return this.batchConsumer?.isHealthy()
    }
}
