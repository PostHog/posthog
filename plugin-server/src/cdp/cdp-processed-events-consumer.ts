import { features, librdkafkaVersion, Message } from 'node-rdkafka'
import { Histogram } from 'prom-client'

import { KAFKA_CDP_FUNCTION_CALLBACKS, KAFKA_EVENTS_JSON, KAFKA_LOG_ENTRIES } from '../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars, createRdProducerConfigFromEnvVars } from '../kafka/config'
import { createKafkaProducer } from '../kafka/producer'
import { addSentryBreadcrumbsEventListeners } from '../main/ingestion-queues/kafka-metrics'
import { runInstrumentedFunction } from '../main/utils'
import { GroupTypeToColumnIndex, Hub, PluginsServerConfig, RawClickHouseEvent, TeamId } from '../types'
import { KafkaProducerWrapper } from '../utils/db/kafka-producer-wrapper'
import { PostgresRouter } from '../utils/db/postgres'
import { status } from '../utils/status'
import { AppMetrics } from '../worker/ingestion/app-metrics'
import { GroupTypeManager } from '../worker/ingestion/group-type-manager'
import { OrganizationManager } from '../worker/ingestion/organization-manager'
import { TeamManager } from '../worker/ingestion/team-manager'
import { RustyHook } from '../worker/rusty-hook'
import { AsyncFunctionExecutor } from './async-function-executor'
import { HogExecutor } from './hog-executor'
import { HogFunctionManager } from './hog-function-manager'
import {
    HogFunctionInvocationAsyncResponse,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionMessageToQueue,
} from './types'
import { convertToHogFunctionInvocationGlobals } from './utils'

// Must require as `tsc` strips unused `import` statements and just requiring this seems to init some globals
require('@sentry/tracing')

// WARNING: Do not change this - it will essentially reset the consumer
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

abstract class CdpConsumerBase {
    batchConsumer?: BatchConsumer
    teamManager: TeamManager
    organizationManager: OrganizationManager
    groupTypeManager: GroupTypeManager
    hogFunctionManager: HogFunctionManager
    asyncFunctionExecutor?: AsyncFunctionExecutor
    hogExecutor: HogExecutor
    appMetrics?: AppMetrics
    isStopping = false

    protected kafkaProducer?: KafkaProducerWrapper
    protected abstract name: string
    protected abstract topic: string
    protected abstract consumerGroupId: string

    constructor(protected config: PluginsServerConfig, protected hub?: Hub) {
        const postgres = hub?.postgres ?? new PostgresRouter(config)

        this.teamManager = new TeamManager(postgres, config)
        this.organizationManager = new OrganizationManager(postgres, this.teamManager)
        this.groupTypeManager = new GroupTypeManager(postgres, this.teamManager)
        this.hogFunctionManager = new HogFunctionManager(postgres, config)
        this.hogExecutor = new HogExecutor(this.config, this.hogFunctionManager)
    }

    public abstract handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void>

    protected async processInvocationResults(results: HogFunctionInvocationResult[]): Promise<void> {
        // Processes any async functions and queues up produced messages

        // TODO: Follow up - process metrics from the invocationResults
        await runInstrumentedFunction({
            statsKey: `cdpFunctionExecutor.handleEachBatch.produceResults`,
            func: async () => {
                const messagesToProduce: HogFunctionMessageToQueue[] = []

                await Promise.all(
                    results.map(async (result) => {
                        result.logs.forEach((x) => {
                            messagesToProduce.push({
                                topic: KAFKA_LOG_ENTRIES,
                                value: x,
                                key: x.instance_id,
                            })
                        })

                        if (result.asyncFunction) {
                            const res = await this.asyncFunctionExecutor!.execute(result.asyncFunction)

                            if (res) {
                                messagesToProduce.push(res)
                            }
                        }
                    })
                )

                await Promise.all(
                    messagesToProduce.map((x) =>
                        this.kafkaProducer!.produce({
                            topic: x.topic,
                            value: Buffer.from(JSON.stringify(x.value)),
                            key: x.key,
                            waitForAck: true,
                        })
                    )
                )
            },
        })
    }

    public async start(): Promise<void> {
        status.info('🔁', `${this.name} - starting`, {
            librdKafkaVersion: librdkafkaVersion,
            kafkaCapabilities: features,
        })

        // NOTE: This is the only place where we need to use the shared server config
        const globalConnectionConfig = createRdConnectionConfigFromEnvVars(this.config)
        const globalProducerConfig = createRdProducerConfigFromEnvVars(this.config)

        await this.hogFunctionManager.start()

        this.kafkaProducer = new KafkaProducerWrapper(
            await createKafkaProducer(globalConnectionConfig, globalProducerConfig)
        )

        const rustyHook = this.hub?.rustyHook ?? new RustyHook(this.config)
        this.asyncFunctionExecutor = new AsyncFunctionExecutor(this.config, rustyHook)

        this.appMetrics =
            this.hub?.appMetrics ??
            new AppMetrics(
                this.kafkaProducer,
                this.config.APP_METRICS_FLUSH_FREQUENCY_MS,
                this.config.APP_METRICS_FLUSH_MAX_QUEUE_SIZE
            )
        this.kafkaProducer.producer.connect()

        this.batchConsumer = await startBatchConsumer({
            connectionConfig: createRdConnectionConfigFromEnvVars(this.config),
            groupId: this.consumerGroupId,
            topic: this.topic,
            autoCommit: true,
            sessionTimeout: this.config.KAFKA_CONSUMPTION_SESSION_TIMEOUT_MS,
            maxPollIntervalMs: this.config.KAFKA_CONSUMPTION_MAX_POLL_INTERVAL_MS,
            // the largest size of a message that can be fetched by the consumer.
            // the largest size our MSK cluster allows is 20MB
            // we only use 9 or 10MB but there's no reason to limit this 🤷️
            consumerMaxBytes: this.config.KAFKA_CONSUMPTION_MAX_BYTES,
            consumerMaxBytesPerPartition: this.config.KAFKA_CONSUMPTION_MAX_BYTES_PER_PARTITION,
            // our messages are very big, so we don't want to buffer too many
            // queuedMinMessages: this.config.KAFKA_QUEUE_SIZE,
            consumerMaxWaitMs: this.config.KAFKA_CONSUMPTION_MAX_WAIT_MS,
            consumerErrorBackoffMs: this.config.KAFKA_CONSUMPTION_ERROR_BACKOFF_MS,
            fetchBatchSize: this.config.INGESTION_BATCH_SIZE,
            batchingTimeoutMs: this.config.KAFKA_CONSUMPTION_BATCHING_TIMEOUT_MS,
            topicCreationTimeoutMs: this.config.KAFKA_TOPIC_CREATION_TIMEOUT_MS,
            eachBatch: async (messages, { heartbeat }) => {
                status.info('🔁', `${this.name} - handling batch`, {
                    size: messages.length,
                })

                histogramKafkaBatchSize.observe(messages.length)
                histogramKafkaBatchSizeKb.observe(messages.reduce((acc, m) => (m.value?.length ?? 0) + acc, 0) / 1024)

                return await this.handleEachBatch(messages, heartbeat)
            },
            callEachBatchWhenEmpty: false,
        })

        addSentryBreadcrumbsEventListeners(this.batchConsumer.consumer)

        this.batchConsumer.consumer.on('disconnected', async (err) => {
            // since we can't be guaranteed that the consumer will be stopped before some other code calls disconnect
            // we need to listen to disconnect and make sure we're stopped
            status.info('🔁', `${this.name} batch consumer disconnected, cleaning up`, { err })
            await this.stop()
        })
    }

    public async stop(): Promise<void> {
        status.info('🔁', `${this.name} - stopping`)
        this.isStopping = true

        // Mark as stopping so that we don't actually process any more incoming messages, but still keep the process alive
        status.info('🔁', `${this.name} - stopping batch consumer`)
        await this.batchConsumer?.stop()
        status.info('🔁', `${this.name} - stopping kafka producer`)
        await this.kafkaProducer?.disconnect()
        status.info('🔁', `${this.name} - stopping hog function manager`)
        await this.hogFunctionManager.stop()

        status.info('👍', `${this.name} - stopped!`)
    }

    public isHealthy() {
        // TODO: Maybe extend this to check if we are shutting down so we don't get killed early.
        return this.batchConsumer?.isHealthy()
    }
}

export class CdpProcessedEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpProcessedEventsConsumer'
    protected topic = KAFKA_EVENTS_JSON
    protected consumerGroupId = 'cdp-processed-events-consumer'

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        await runInstrumentedFunction({
            statsKey: `cdpFunctionExecutor.handleEachBatch`,
            sendTimeoutGuardToSentry: false,
            func: async () => {
                let events: HogFunctionInvocationGlobals[] = []

                await runInstrumentedFunction({
                    statsKey: `cdpFunctionExecutor.handleEachBatch.parseKafkaMessages`,
                    func: async () => {
                        events = await this.convertToHogFunctionInvocationGlobals(messages)
                    },
                })
                heartbeat()

                const invocationResults: HogFunctionInvocationResult[] = []

                if (!events.length) {
                    return
                }

                await runInstrumentedFunction({
                    statsKey: `cdpFunctionExecutor.handleEachBatch.consumeBatch`,
                    func: async () => {
                        const results = await Promise.all(
                            events.map((e) => this.hogExecutor.executeMatchingFunctions(e))
                        )
                        invocationResults.push(...results.flat())
                    },
                })

                heartbeat()

                await this.processInvocationResults(invocationResults)
            },
        })
    }

    private async convertToHogFunctionInvocationGlobals(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []
        await Promise.all(
            messages.map(async (message) => {
                try {
                    const clickHouseEvent = JSON.parse(message.value!.toString()) as RawClickHouseEvent

                    if (!this.hogFunctionManager.teamHasHogFunctions(clickHouseEvent.team_id)) {
                        // No need to continue if the team doesn't have any functions
                        return
                    }

                    let groupTypes: GroupTypeToColumnIndex | undefined = undefined

                    if (
                        await this.organizationManager.hasAvailableFeature(clickHouseEvent.team_id, 'group_analytics')
                    ) {
                        // If the organization has group analytics enabled then we enrich the event with group data
                        groupTypes = await this.groupTypeManager.fetchGroupTypes(clickHouseEvent.team_id)
                    }

                    const team = await this.teamManager.fetchTeam(clickHouseEvent.team_id)
                    if (!team) {
                        return
                    }
                    events.push(
                        convertToHogFunctionInvocationGlobals(
                            clickHouseEvent,
                            team,
                            this.config.SITE_URL ?? 'http://localhost:8000',
                            groupTypes
                        )
                    )
                } catch (e) {
                    status.error('Error parsing message', e)
                }
            })
        )

        return events
    }
}

export class CdpFunctionCallbackConsumer extends CdpConsumerBase {
    protected name = 'CdpFunctionCallbackConsumer'
    protected topic = KAFKA_CDP_FUNCTION_CALLBACKS
    protected consumerGroupId = 'cdp-function-callback-consumer'

    public async handleEachBatch(messages: Message[], heartbeat: () => void): Promise<void> {
        await runInstrumentedFunction({
            statsKey: `cdpFunctionExecutor.handleEachBatch`,
            sendTimeoutGuardToSentry: false,
            func: async () => {
                let events: HogFunctionInvocationAsyncResponse[] = []

                await runInstrumentedFunction({
                    statsKey: `cdpFunctionExecutor.handleEachBatch.parseKafkaMessages`,
                    func: () => {
                        events = this.parseMessages(messages)
                        return Promise.resolve()
                    },
                })
                heartbeat()

                const invocationResults: HogFunctionInvocationResult[] = []

                if (!events.length) {
                    return
                }

                await runInstrumentedFunction({
                    statsKey: `cdpFunctionExecutor.handleEachBatch.consumeBatch`,
                    func: async () => {
                        const results = await Promise.all(events.map((e) => this.hogExecutor.executeAsyncResponse(e)))
                        invocationResults.push(...results.flat())
                    },
                })

                heartbeat()

                await this.processInvocationResults(invocationResults)
            },
        })
    }

    private parseMessages(messages: Message[]): HogFunctionInvocationAsyncResponse[] {
        const events: HogFunctionInvocationAsyncResponse[] = []
        messages.map((message) => {
            try {
                const event = JSON.parse(message.value!.toString()) as unknown

                // TODO: Check the message really is a HogFunctionInvocationAsyncResponse
                events.push(event as HogFunctionInvocationAsyncResponse)
            } catch (e) {
                status.error('Error parsing message', e)
            }
        })

        return events
    }
}
