import { Message } from 'node-rdkafka'

import { KAFKA_CDP_INTERNAL_EVENTS } from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'

import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { isManagedAlertInternalEvent } from '../managed-alert-events'
import { CdpInternalEventSchema } from '../schema'
import { HogFlowInvocationPipeline } from '../services/hog-flow-invocation-pipeline.service'
import { HogFunctionInvocationPipeline } from '../services/hog-function-invocation-pipeline.service'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { convertInternalEventToHogFunctionInvocationGlobals } from '../utils'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

const SLACK_MESSAGE_RECEIVED_EVENT = '$slack_message_received'

// The event that starts each trigger type. Type alone would match every other signal on this topic.
const INTERNAL_EVENT_TRIGGER_EVENTS = new Map([['slack-message', SLACK_MESSAGE_RECEIVED_EVENT]])

export class CdpInternalEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpInternalEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['internal_destination']

    protected hogQueue: JobQueue
    protected hogflowQueue: JobQueue
    protected kafkaConsumer: KafkaConsumerInterface
    private hogFunctionPipeline: HogFunctionInvocationPipeline
    private hogFlowPipeline: HogFlowInvocationPipeline

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        jobQueues: { hogQueue: JobQueue; hogflowQueue: JobQueue }
    ) {
        super(config, deps)
        this.hogQueue = jobQueues.hogQueue
        this.hogflowQueue = jobQueues.hogflowQueue
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-internal-events-consumer',
            topic: KAFKA_CDP_INTERNAL_EVENTS,
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

        await this.groupsManager.addGroupsToGlobalsList(invocationGlobals)

        const ownSlackMessages = await this.findOwnSlackMessages(invocationGlobals)

        const [hogInvocations, hogflowInvocations] = await Promise.all([
            this.hogFunctionPipeline.buildInvocations(invocationGlobals, {
                hogTypes: this.hogTypes,
                filterFn: () => true,
                invocationFilterFn: (fn, globals) => {
                    if (!isManagedAlertInternalEvent(globals.event.event)) {
                        return true
                    }
                    const alertId = globals.event.properties?.alert_id
                    return Boolean(
                        typeof alertId === 'string' &&
                            fn.filters?.events?.some((event) => event.id === globals.event.event) &&
                            fn.filters?.properties?.some(
                                (property) =>
                                    property.type === 'event' &&
                                    property.key === 'alert_id' &&
                                    property.operator === 'exact' &&
                                    property.value === alertId
                            )
                    )
                },
            }),
            this.hogFlowPipeline.buildInvocations(invocationGlobals, {
                eligibilityFn: (flow, globals) =>
                    INTERNAL_EVENT_TRIGGER_EVENTS.get(flow.trigger.type) === globals.event.event &&
                    !ownSlackMessages.has(globals),
            }),
        ])

        const invocationsToBeQueued = [...hogInvocations, ...hogflowInvocations]

        // Emit a `running` lifecycle row per freshly-created invocation so the runs UI shows these as
        // in-flight, matching the event and warehouse consumers. The terminal row is queued later by
        // the cyclotron worker; both collapse under the same `invocation_id` via ReplacingMergeTree.
        for (const invocation of hogflowInvocations) {
            this.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')
        }

        return {
            backgroundTask: Promise.all([
                instrumentFn({ key: 'cdp.background_task.queue_invocations', sendException: false }, () =>
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
            invocations: invocationsToBeQueued,
        }
    }

    /**
     * Slack messages PostHog's own app posted, resolved through the integration the emit stamped
     * on the event.
     *
     * A workflow that replies in Slack sees its own reply arrive back on this topic, so without
     * this it retriggers itself forever. This is part of eligibility rather than a trigger's stored
     * filters, which a workflow created through the API or MCP would not carry.
     */
    private async findOwnSlackMessages(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<Set<HogFunctionInvocationGlobals>> {
        const candidates = invocationGlobals.filter(
            (globals) =>
                globals.event.event === SLACK_MESSAGE_RECEIVED_EVENT &&
                typeof globals.event.properties.app_id === 'string' &&
                typeof globals.event.properties.integration_id === 'number'
        )

        if (!candidates.length) {
            return new Set()
        }

        const integrations = await this.deps.integrationManager.getMany([
            ...new Set(candidates.map((globals) => globals.event.properties.integration_id as number)),
        ])

        return new Set(
            candidates.filter(
                (globals) =>
                    integrations[globals.event.properties.integration_id as number]?.config?.app_id ===
                    globals.event.properties.app_id
            )
        )
    }

    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []
        await Promise.all(
            messages.map(async (message) => {
                try {
                    const kafkaEvent = parseJSON(message.value!.toString()) as unknown
                    const event = CdpInternalEventSchema.parse(kafkaEvent)

                    const [teamHogFunctions, teamHogFlows, team] = await Promise.all([
                        this.hogFunctionManager.getHogFunctionsForTeam(event.team_id, this.hogTypes),
                        this.hogFlowManager.getHogFlowsForTeam(event.team_id),
                        this.deps.teamManager.getTeam(event.team_id),
                    ])

                    if ((!teamHogFunctions.length && !teamHogFlows.length) || !team) {
                        return
                    }

                    events.push(convertInternalEventToHogFunctionInvocationGlobals(event, team, this.config.SITE_URL))
                } catch (e) {
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return events
    }

    public override async start(): Promise<void> {
        await super.start()
        await Promise.all([this.hogQueue.startAsProducer(), this.hogflowQueue.startAsProducer()])
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, { size: messages.length })
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
        await Promise.all([this.hogQueue.stopProducer(), this.hogflowQueue.stopProducer()])
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
