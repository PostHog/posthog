import { Message } from 'node-rdkafka'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'

import { KAFKA_CDP_INTERNAL_EVENTS } from '../../config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, PluginsServerConfig } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'
import { CdpInternalEventSchema } from '../schema'
import { HogFunctionInvocationPipeline } from '../services/hog-function-invocation-pipeline.service'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { CyclotronJobInvocation, HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { convertInternalEventToHogFunctionInvocationGlobals } from '../utils'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

export class CdpInternalEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpInternalEventsConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['internal_destination']

    protected cyclotronJobQueue: CyclotronJobQueue
    protected kafkaConsumer: KafkaConsumerInterface
    private hogFunctionPipeline: HogFunctionInvocationPipeline

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.cyclotronJobQueue = new CyclotronJobQueue(config.CONSUMER_BATCH_SIZE, config.KAFKA_CLIENT_RACK, config)
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-internal-events-consumer',
            topic: KAFKA_CDP_INTERNAL_EVENTS,
        })
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
    }

    public async processBatch(
        invocationGlobals: HogFunctionInvocationGlobals[]
    ): Promise<{ backgroundTask: Promise<any>; invocations: CyclotronJobInvocation[] }> {
        if (!invocationGlobals.length) {
            return { backgroundTask: Promise.resolve(), invocations: [] }
        }

        await this.groupsManager.addGroupsToGlobalsList(invocationGlobals)

        const invocationsToBeQueued = await this.hogFunctionPipeline.buildInvocations(invocationGlobals, {
            hogTypes: this.hogTypes,
            filterFn: () => true,
        })

        return {
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

    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<HogFunctionInvocationGlobals[]> {
        const events: HogFunctionInvocationGlobals[] = []
        await Promise.all(
            messages.map(async (message) => {
                try {
                    const kafkaEvent = parseJSON(message.value!.toString()) as unknown
                    const event = CdpInternalEventSchema.parse(kafkaEvent)

                    const [teamHogFunctions, team] = await Promise.all([
                        this.hogFunctionManager.getHogFunctionsForTeam(event.team_id, this.hogTypes),
                        this.deps.teamManager.getTeam(event.team_id),
                    ])

                    if (!teamHogFunctions.length || !team) {
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
        await this.cyclotronJobQueue.startAsProducer()
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
        await this.cyclotronJobQueue.stop()
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
