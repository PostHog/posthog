import { convertJSToHog } from '@posthog/hogvm'
import express from 'express'
import { features, librdkafkaVersion, Message } from 'node-rdkafka'
import { Histogram } from 'prom-client'

import { KAFKA_CDP_FUNCTION_CALLBACKS, KAFKA_EVENTS_JSON, KAFKA_LOG_ENTRIES } from '../config/kafka-topics'
import { BatchConsumer, startBatchConsumer } from '../kafka/batch-consumer'
import { createRdConnectionConfigFromEnvVars, createRdProducerConfigFromEnvVars } from '../kafka/config'
import { createKafkaProducer } from '../kafka/producer'
import { addSentryBreadcrumbsEventListeners } from '../main/ingestion-queues/kafka-metrics'
import { runInstrumentedFunction } from '../main/utils'
import { GroupTypeToColumnIndex, Hub, PluginsServerConfig, RawClickHouseEvent, TeamId, TimestampFormat } from '../types'
import { KafkaProducerWrapper } from '../utils/db/kafka-producer-wrapper'
import { PostgresRouter } from '../utils/db/postgres'
import { status } from '../utils/status'
import { castTimestampOrNow } from '../utils/utils'
import { AppMetrics } from '../worker/ingestion/app-metrics'
import { GroupTypeManager } from '../worker/ingestion/group-type-manager'
import { OrganizationManager } from '../worker/ingestion/organization-manager'
import { TeamManager } from '../worker/ingestion/team-manager'
import { RustyHook } from '../worker/rusty-hook'
import { AsyncFunctionExecutor } from './async-function-executor'
import { addLog, HogExecutor } from './hog-executor'
import { HogFunctionManager } from './hog-function-manager'
import {
    HogFunctionInvocation,
    HogFunctionInvocationAsyncResponse,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionMessageToQueue,
    HogFunctionType,
} from './types'
import { convertToHogFunctionInvocationGlobals, convertToParsedClickhouseEvent } from './utils'

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
                        // Tricky: We want to pull all the logs out as we don't want them to be passed around to any subsequent functions
                        const logs = result.logs
                        result.logs = []

                        logs.forEach((x) => {
                            const sanitized = {
                                ...x,
                                timestamp: castTimestampOrNow(x.timestamp, TimestampFormat.ClickHouse),
                            }
                            // Convert timestamps to ISO strings
                            messagesToProduce.push({
                                topic: KAFKA_LOG_ENTRIES,
                                value: sanitized,
                                key: x.instance_id,
                            })
                        })

                        if (result.asyncFunctionRequest) {
                            const res = await this.asyncFunctionExecutor!.execute(result)

                            if (res) {
                                messagesToProduce.push({
                                    topic: KAFKA_CDP_FUNCTION_CALLBACKS,
                                    value: res,
                                    key: res.id,
                                })
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
                            convertToParsedClickhouseEvent(clickHouseEvent),
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

    public addApiRoutes(app: express.Application) {
        app.post('/api/projects/:team_id/hog_functions/:id/invocations', async (req, res): Promise<void> => {
            try {
                const { id, team_id } = req.params
                const { event, mock_async_functions, configuration } = req.body

                status.info('⚡️', 'Received invocation', { id, team_id, body: req.body })

                if (!event) {
                    res.status(400).json({ error: 'Missing event' })
                    return
                }

                const [hogFunction, team] = await Promise.all([
                    this.hogFunctionManager.fetchHogFunction(req.params.id),
                    this.teamManager.fetchTeam(parseInt(team_id)),
                ]).catch(() => {
                    return [null, null]
                })
                if (!hogFunction || !team || hogFunction.team_id !== team.id) {
                    res.status(404).json({ error: 'Hog function not found' })
                    return
                }

                let groupTypes: GroupTypeToColumnIndex | undefined = undefined

                if (await this.organizationManager.hasAvailableFeature(team.id, 'group_analytics')) {
                    // If the organization has group analytics enabled then we enrich the event with group data
                    groupTypes = await this.groupTypeManager.fetchGroupTypes(team.id)
                }

                const globals = convertToHogFunctionInvocationGlobals(
                    event,
                    team,
                    this.config.SITE_URL ?? 'http://localhost:8000',
                    groupTypes
                )

                globals.source = {
                    name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                    url: `${globals.project.url}/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
                }

                const invocation: HogFunctionInvocation = {
                    id,
                    globals: globals,
                    teamId: team.id,
                    hogFunctionId: id,
                    logs: [],
                    timings: [],
                }

                // We use the provided config if given, otherwise the function's config
                const compoundConfiguration: HogFunctionType = {
                    ...hogFunction,
                    ...(configuration ?? {}),
                }

                // TODO: Type the configuration better so we don't make mistakes here
                await this.hogFunctionManager.enrichWithIntegrations([compoundConfiguration])

                let response = this.hogExecutor.execute(compoundConfiguration, invocation)

                while (response.asyncFunctionRequest) {
                    const asyncFunctionRequest = response.asyncFunctionRequest

                    if (mock_async_functions || asyncFunctionRequest.name !== 'fetch') {
                        addLog(response, 'info', `Async function '${asyncFunctionRequest.name}' was mocked`)

                        // Add the state, simulating what executeAsyncResponse would do
                        asyncFunctionRequest.vmState.stack.push(convertJSToHog({ status: 200, body: {} }))
                    } else {
                        const asyncRes = await this.asyncFunctionExecutor!.execute(response, {
                            sync: true,
                        })

                        if (!asyncRes || asyncRes.asyncFunctionResponse.error) {
                            addLog(response, 'error', 'Failed to execute async function')
                        }
                        asyncFunctionRequest.vmState.stack.push(
                            convertJSToHog(asyncRes?.asyncFunctionResponse.vmResponse ?? null)
                        )
                        response.timings.push(...(asyncRes?.asyncFunctionResponse.timings ?? []))
                    }

                    // Clear it so we can't ever end up in a loop
                    delete response.asyncFunctionRequest

                    response = this.hogExecutor.execute(compoundConfiguration, response, asyncFunctionRequest.vmState)
                }

                res.json({
                    status: response.finished ? 'success' : 'error',
                    error: String(response.error),
                    logs: response.logs,
                })
            } catch (e) {
                console.error(e)
                res.status(500).json({ error: e.message })
            }
        })
    }
}
