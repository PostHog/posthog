import { Message } from 'node-rdkafka'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { convertToHogFunctionInvocationGlobals } from '../../cdp/utils'
import { KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, PluginsServerConfig, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { HogFlowInvocationPipeline } from '../services/hog-flow-invocation-pipeline.service'
import { HogFunctionInvocationPipeline } from '../services/hog-function-invocation-pipeline.service'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { CyclotronJobInvocation, HogFunctionInvocationGlobals, HogFunctionType, HogFunctionTypeType } from '../types'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

export class CdpEventsConsumer<
    TConfig extends PluginsServerConfig = PluginsServerConfig,
> extends CdpConsumerBase<TConfig> {
    protected name = 'CdpEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']
    private cyclotronJobQueue: CyclotronJobQueue
    protected kafkaConsumer: KafkaConsumerInterface

    private hogFunctionPipeline: HogFunctionInvocationPipeline
    private hogFlowPipeline: HogFlowInvocationPipeline

    constructor(
        config: TConfig,
        deps: CdpConsumerBaseDeps,
        topic: string = KAFKA_EVENTS_JSON,
        groupId: string = 'cdp-processed-events-consumer'
    ) {
        super(config, deps)
        this.cyclotronJobQueue = new CyclotronJobQueue(config.CONSUMER_BATCH_SIZE, config.KAFKA_CLIENT_RACK, config)
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
                filterFn: this.filterHogFunction.bind(this),
            }),
            this.hogFlowPipeline.buildInvocations(invocationGlobals),
        ])

        const invocationsToBeQueued = [...hogInvocations, ...hogflowInvocations]

        return {
            // This is all IO so we can set them off in the background and start processing the next batch
            backgroundTask: Promise.all([
                instrumentFn({ key: 'cdp.background_task.queue_invocations', sendException: false }, () =>
                    this.cyclotronJobQueue.queueInvocations(invocationsToBeQueued)
                ),
                instrumentFn({ key: 'cdp.background_task.monitoring_flush', sendException: false }, async () => {
                    try {
                        await this.hogFunctionMonitoringService.flush()
                    } catch (err) {
                        captureException(err)
                        logger.error('🔴', 'Error producing queued messages for monitoring', { err })
                    }
                }),
            ]),
            invocations: invocationsToBeQueued,
        }
    }

    protected filterHogFunction(hogFunction: HogFunctionType): boolean {
        // By default we filter for those with no filters or filters specifically for events
        return (hogFunction.filters?.source ?? 'events') === 'events'
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

    public override async start(): Promise<void> {
        await super.start()
        // Make sure we are ready to produce to cyclotron first
        await this.cyclotronJobQueue.startAsProducer()
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
        logger.info('💤', 'Stopping cyclotron job queue...')
        await this.cyclotronJobQueue.stop()
        logger.info('💤', 'Stopping consumer...')
        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
