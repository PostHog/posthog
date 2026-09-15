import { Message } from 'node-rdkafka'

import { KAFKA_EVENTS_JSON } from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { convertToHogFunctionInvocationGlobals } from '../../cdp/utils'
import { HealthCheckResult, PluginsServerConfig, RawClickHouseEvent } from '../../types'
import { CDP_EVENTS_DLQ_OUTPUT } from '../outputs/outputs'
import { CdpDeadLetterService } from '../services/dead-letter/cdp-dead-letter.service'
import { HogFlowInvocationPipeline } from '../services/hog-flow-invocation-pipeline.service'
import { HogFunctionInvocationPipeline } from '../services/hog-function-invocation-pipeline.service'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'
import { PUSH_NOTIFICATION_OPENED_EVENT, buildPushOpenedMetric } from './push-open-tracking'

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
    private deadLetterService: CdpDeadLetterService
    /** The message each set of globals was built from, so a failure can find its bytes. */
    private messageByGlobals = new WeakMap<HogFunctionInvocationGlobals, Message>()

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
        this.deadLetterService = new CdpDeadLetterService(config, {
            outputs: this.outputs,
            output: CDP_EVENTS_DLQ_OUTPUT,
            consumerGroup: groupId,
            resolveMessage: (globals) => this.messageByGlobals.get(globals),
        })
        this.hogFunctionPipeline = new HogFunctionInvocationPipeline(config, {
            hogFunctionManager: this.hogFunctionManager,
            hogInputsService: this.hogInputsService,
            hogWatcher: this.hogWatcher,
            hogWatcherMirror: this.hogWatcherMirror,
            hogMasker: this.hogMasker,
            hogFunctionMonitoringService: this.hogFunctionMonitoringService,
            cdpUsageReporter: this.cdpUsageReporter,
            quotaLimiting: deps.quotaLimiting,
            redis: this.redis,
            valkeyShadow: this.valkeyShadow,
            deadLetterService: this.deadLetterService,
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
            deadLetterService: this.deadLetterService,
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

        // Turn any $push_notification_opened events in this batch into `push_opened` app-metrics. Queued
        // here (synchronously) so the monitoring flush in the background task below picks them up.
        await this.trackPushNotificationOpens(invocationGlobals)

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

    // Resolve each $push_notification_opened event's workflow and queue its push_opened app-metric.
    // The attribution + spoof guard live in buildPushOpenedMetric (pure + unit-tested).
    private async trackPushNotificationOpens(globals: HogFunctionInvocationGlobals[]): Promise<void> {
        const opens = globals.filter((g) => g.event.event === PUSH_NOTIFICATION_OPENED_EVENT)
        if (!opens.length) {
            return
        }
        // Match each open's workflow id against the flows its own team owns, which the hog flow pipeline
        // already loaded for this batch (warm by-team cache). Resolving against that bounded, team-owned
        // set rather than looking up the client-supplied id directly keeps a spoofed id from hitting
        // Postgres or polluting the shared by-id cache with negative entries. Best-effort: a lookup
        // failure here must not abort the batch (that would stall all event processing and force a replay).
        try {
            const teamIds = Array.from(new Set(opens.map((g) => g.project.id)))
            const flowsByTeam = await this.hogFlowManager.getHogFlowsForTeams(teamIds)
            for (const g of opens) {
                const workflowId = g.event.properties['$notification_workflow_id']
                if (typeof workflowId !== 'string') {
                    continue
                }
                const flow = (flowsByTeam[g.project.id] ?? []).find((f) => f.id === workflowId) ?? null
                const metric = buildPushOpenedMetric(g.event.properties, g.project.id, flow)
                if (metric) {
                    this.hogFunctionMonitoringService.queueAppMetric(metric, 'hog_flow')
                }
            }
        } catch (error) {
            logger.error('[CdpEventsConsumer] Failed to track push notification opens', { error })
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

                    const globals = convertToHogFunctionInvocationGlobals(clickHouseEvent, team, this.config.SITE_URL)
                    // The one place holding both. A failure found later in the pipeline carries
                    // these globals, and this is how it gets back to the bytes to park.
                    this.messageByGlobals.set(globals, message)
                    events.push(globals)
                } catch (e) {
                    // A dependency outage is not a poison message. Rethrowing fails the batch, so the
                    // offsets stay put and the consumer retries, instead of dropping every event of a
                    // team for the length of a Postgres blip.
                    if (e?.isRetriable === true) {
                        throw e
                    }
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                    // Unreadable for this code version. Park the bytes rather than dropping them: a
                    // schema we cannot read today is often one a later version can.
                    this.deadLetterService.recordMessageFailure(message, {
                        step: 'parse',
                        error: e.message,
                    })
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
        await this.deadLetterService.checkTopic()
        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpConsumer.handleEachBatch', async () => {
                const invocationGlobals = await this._parseKafkaBatch(messages)
                const { backgroundTask } = await this.processBatch(invocationGlobals)
                // Awaited, not backgrounded: the offsets for these messages are stored once this
                // handler resolves, so a record has to exist by then or the event is gone.
                await this.deadLetterService.produceForBatch(messages)

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
