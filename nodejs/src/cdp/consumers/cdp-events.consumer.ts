import { Message } from 'node-rdkafka'

import { KAFKA_EVENTS_JSON } from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { convertToHogFunctionInvocationGlobals } from '../../cdp/utils'
import { HealthCheckResult, PluginsServerConfig, RawClickHouseEvent } from '../../types'
import { HogFlowInvocationPipeline } from '../services/hog-flow-invocation-pipeline.service'
import { HogFunctionInvocationPipeline } from '../services/hog-function-invocation-pipeline.service'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

export class CdpEventsConsumer<
    TConfig extends PluginsServerConfig = PluginsServerConfig,
> extends CdpConsumerBase<TConfig> {
    protected name = 'CdpEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']
    protected hogQueue: JobQueue
    protected hogflowQueue: JobQueue
    protected kafkaConsumer: KafkaConsumerInterface

    private hogFunctionPipeline: HogFunctionInvocationPipeline
    private hogFlowPipeline: HogFlowInvocationPipeline

    constructor(
        config: TConfig,
        deps: CdpConsumerBaseDeps,
        jobQueues: { hogQueue: JobQueue; hogflowQueue: JobQueue },
        topic: string = KAFKA_EVENTS_JSON,
        groupId: string = 'cdp-processed-events-consumer'
    ) {
        super(config, deps)
        this.hogQueue = jobQueues.hogQueue
        this.hogflowQueue = jobQueues.hogflowQueue
        this.kafkaConsumer = createKafkaConsumer({ groupId, topic })
        this.hogFunctionPipeline = new HogFunctionInvocationPipeline(config, {
            hogFunctionManager: this.hogFunctionManager,
            hogExecutor: this.hogExecutor,
            hogWatcher: this.hogWatcher,
            hogWatcherMirror: this.hogWatcherMirror,
            hogMasker: this.hogMasker,
            hogFunctionMonitoringService: this.hogFunctionMonitoringService,
            quotaLimiting: deps.quotaLimiting,
            redis: this.redis,
            valkeyShadow: this.valkeyShadow,
        })
        this.hogFlowPipeline = new HogFlowInvocationPipeline(config, {
            hogFlowManager: this.hogFlowManager,
            hogFlowExecutor: this.hogFlowExecutor,
            hogWatcher: this.hogWatcher,
            hogWatcherMirror: this.hogWatcherMirror,
            hogMasker: this.hogMasker,
            hogFunctionMonitoringService: this.hogFunctionMonitoringService,
            quotaLimiting: deps.quotaLimiting,
            redis: this.redis,
            valkeyShadow: this.valkeyShadow,
        })
    }

    public async processBatch(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<{ backgroundTask: Promise<any>; invocations: CyclotronJobInvocation[] }> {
        if (!invocationGlobals.length) {
            return { backgroundTask: Promise.resolve(), invocations: [] }
        }

        // TODO: Add a helper to hog functions to determine if they require groups or not and then only load those
        await this.groupsManager.addGroupsToGlobalsList(invocationGlobals)

        const [hogInvocations, hogflowInvocations] = await Promise.all([
            this.hogFunctionPipeline.buildInvocations(invocationGlobals, {
                hogTypes: this.hogTypes,
                filterFn: (fn) => (fn.filters?.source ?? 'events') === 'events',
            }),
            // Source-compatibility lives in the consumer. The events consumer matches event-triggered
            // flows only; other trigger types (data-warehouse-table, batch, schedule, webhook, manual)
            // are dispatched from their respective consumers and never reach the executor from here.
            this.hogFlowPipeline.buildInvocations(invocationGlobals, {
                eligibilityFn: (flow) => flow.trigger.type === 'event',
            }),
        ])

        const invocationsToBeQueued = [...hogInvocations, ...hogflowInvocations]

        // Emit a `running` lifecycle row for each freshly-created invocation.
        // This fires ONCE per invocation_id at creation — not on every dequeue
        // — so the runs UI can show in-flight work without us writing duplicate
        // running rows across fetch retries. The terminal row is queued later
        // by the cyclotron worker; both collapse under the same `invocation_id`
        // via ReplacingMergeTree, with the terminal row's later `version`
        // superseding the running row on FINAL queries.
        for (const invocation of invocationsToBeQueued) {
            this.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
        }

        return {
            // This is all IO so we can set them off in the background and start processing the next batch
            backgroundTask: Promise.all([
                instrumentFn({ key: 'cdp.background_task.queue_hog_invocations', sendException: false }, () =>
                    this.hogQueue.queueInvocations(hogInvocations)
                ),
                instrumentFn({ key: 'cdp.background_task.queue_hogflow_invocations', sendException: false }, () =>
                    this.hogflowQueue.queueInvocations(hogflowInvocations)
                ),
                instrumentFn({ key: 'cdp.background_task.monitoring_flush', sendException: false }, async () => {
                    try {
                        await this.hogFunctionMonitoringService.flush()
                    } catch (err) {
                        captureException(err)
                        logger.error('🔴', 'Error producing queued messages for monitoring', { err })
                    }
                }),
                instrumentFn({ key: 'cdp.background_task.lifecycle_running_flush', sendException: false }, () =>
                    this.invocationResultsService.invocationResultsRowsService.flush()
                ),
            ]),
            invocations: [...hogInvocations, ...hogflowInvocations],
        }
    }

    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                    const [teamHogFunctions, teamHogFlows, team] = await Promise.all([
                        this.hogFunctionManager.getHogFunctionsForTeam(clickHouseEvent.team_id, this.hogTypes),
                        this.hogFlowManager.getHogFlowsForTeam(clickHouseEvent.team_id),
                        this.deps.teamManager.getTeam(clickHouseEvent.team_id),
                    ])

                    if ((!teamHogFunctions.length && !teamHogFlows.length) || !team) {
                        return
                    }

                    events.push(convertToHogFunctionInvocationGlobals(clickHouseEvent, team, this.config.SITE_URL))
                } catch (e) {
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return events
    }

    protected async startQueueProducers(): Promise<void> {
        await Promise.all([this.hogQueue.startAsProducer(), this.hogflowQueue.startAsProducer()])
    }

    protected async stopQueueProducers(): Promise<void> {
        await Promise.all([this.hogQueue.stopProducer(), this.hogflowQueue.stopProducer()])
    }

    public override async start(): Promise<void> {
        await super.start()
        await this.startQueueProducers()
        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpConsumer.handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                const { backgroundTask } = await this.processBatch(invocationGlobals)

                return { backgroundTask }
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        logger.info('💤', 'Stopping job queues...')
        await this.stopQueueProducers()
        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
