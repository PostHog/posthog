import { Message } from 'node-rdkafka'

import { KAFKA_GROUPS } from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { UUIDT } from '~/common/utils/utils'

import { ClickhouseGroup, HealthCheckResult, PluginsServerConfig, Team } from '../../types'
import { HogFunctionInvocationPipeline } from '../services/hog-function-invocation-pipeline.service'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, HogFunctionInvocationGlobals, HogFunctionTypeType } from '../types'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

export class CdpGroupUpdatesConsumer extends CdpConsumerBase {
    protected name = 'CdpGroupUpdatesConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']

    protected hogQueue: JobQueue
    protected kafkaConsumer: KafkaConsumerInterface
    private hogFunctionPipeline: HogFunctionInvocationPipeline

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, hogQueue: JobQueue) {
        super(config, deps)
        this.hogQueue = hogQueue
        this.kafkaConsumer = createKafkaConsumer({
            groupId: 'cdp-group-updates-consumer',
            topic: KAFKA_GROUPS,
        })
        this.hogFunctionPipeline = new HogFunctionInvocationPipeline(config, {
            hogFunctionManager: this.hogFunctionManager,
            hogInputsService: this.hogInputsService,
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

        const invocationsToBeQueued = await this.hogFunctionPipeline.buildInvocations(invocationGlobals, {
            hogTypes: this.hogTypes,
            filterFn: (fn) => fn.filters?.source === 'group-updates',
        })

        return {
            backgroundTask: Promise.all([
                instrumentFn({ key: 'cdp.background_task.queue_invocations', sendException: false }, () =>
                    this.hogQueue.queueInvocations(invocationsToBeQueued)
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
        const globals: HogFunctionInvocationGlobals[] = []
        await Promise.all(
            messages.map(async (message) => {
                try {
                    const data = parseJSON(message.value!.toString()) as ClickhouseGroup

                    const [teamHogFunctions, team] = await Promise.all([
                        this.hogFunctionManager.getHogFunctionsForTeam(data.team_id, this.hogTypes),
                        this.deps.teamManager.getTeam(data.team_id),
                    ])

                    const filteredHogFunctions = teamHogFunctions.filter((fn) => fn.filters?.source === 'group-updates')

                    if (!filteredHogFunctions.length || !team) {
                        return
                    }

                    // Group property filters compile against `groups.<type>`, so a group we can't
                    // name can't be filtered on - drop it rather than invoke with a mislabelled group.
                    const groupType = await this.groupsManager.getGroupTypeName(data.team_id, data.group_type_index)
                    if (!groupType) {
                        return
                    }

                    globals.push(
                        convertClickhouseGroupToInvocationGlobals(
                            data,
                            team,
                            groupType,
                            new Date(message.timestamp ?? Date.now()).toISOString(),
                            this.config.SITE_URL
                        )
                    )
                } catch (e) {
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return globals
    }

    public override async start(): Promise<void> {
        await super.start()
        await this.hogQueue.startAsProducer()
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
        await this.hogQueue.stopProducer()
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}

function convertClickhouseGroupToInvocationGlobals(
    data: ClickhouseGroup,
    team: Team,
    groupType: string,
    timestamp: string,
    siteUrl: string
): HogFunctionInvocationGlobals {
    const projectUrl = `${siteUrl}/project/${team.id}`
    const groupUrl = `${projectUrl}/groups/${data.group_type_index}/${encodeURIComponent(data.group_key)}`

    return {
        project: {
            id: team.id,
            name: team.name,
            url: projectUrl,
        },
        event: {
            uuid: new UUIDT().toString(),
            event: '$group_updated',
            distinct_id: data.group_key,
            properties: {},
            timestamp,
            url: groupUrl,
            elements_chain: '',
        },
        groups: {
            [groupType]: {
                id: data.group_key,
                type: groupType,
                index: data.group_type_index,
                url: groupUrl,
                properties: parseJSON(data.group_properties),
            },
        },
    }
}
