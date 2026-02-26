import { Message } from 'node-rdkafka'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { KAFKA_CDP_BATCH_HOGFLOW_REQUESTS } from '~/config/kafka-topics'
import { HogFlow } from '~/schema/hogflow'
import { parseJSON } from '~/utils/json-parse'
import { captureException } from '~/utils/posthog'

import { InternalFetchService } from '../../common/services/internal-fetch'
import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, PluginsServerConfig, Team } from '../../types'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import { HogFlowBatchPersonQueryService } from '../services/hogflows/hogflow-batch-person-query.service'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { CyclotronJobInvocation, HogFunctionFilters } from '../types'
import { convertBatchHogFlowRequestToHogFunctionInvocationGlobals } from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterParseError } from './metrics'

export interface BatchHogFlowRequest {
    teamId: number
    hogFlowId: HogFlow['id']
    parentRunId: string
    filters: Pick<HogFunctionFilters, 'properties' | 'filter_test_accounts'>
    group_type_index?: number
}

export interface BatchHogFlowRequestMessage {
    batchHogFlowRequest: BatchHogFlowRequest
    team: Team
    hogFlow: HogFlow
}

export class CdpBatchHogFlowRequestsConsumer extends CdpConsumerBase<PluginsServerConfig> {
    protected name = 'CdpBatchHogFlowRequestsConsumer'
    private cyclotronJobQueue: CyclotronJobQueue
    protected kafkaConsumer: KafkaConsumer
    private hogFlowBatchPersonQueryService: HogFlowBatchPersonQueryService

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        topic: string = KAFKA_CDP_BATCH_HOGFLOW_REQUESTS,
        groupId: string = 'cdp-batch-hogflow-requests-consumer'
    ) {
        super(config, deps)
        this.cyclotronJobQueue = new CyclotronJobQueue(config, 'hogflow')
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
        this.hogFlowBatchPersonQueryService = new HogFlowBatchPersonQueryService(
            config.SITE_URL,
            new InternalFetchService(config)
        )
    }

    private createHogFlowInvocation({
        parentRunId,
        hogFlow,
        team,
        personId,
        defaultVariables,
    }: {
        parentRunId: string
        hogFlow: HogFlow
        team: Team
        personId: string
        defaultVariables: Record<string, any>
    }): CyclotronJobInvocation {
        const invocationGlobals = convertBatchHogFlowRequestToHogFunctionInvocationGlobals({
            team: team,
            personId: personId,
            siteUrl: this.config.SITE_URL,
        })

        const filterGlobals = convertToHogFunctionFilterGlobal(invocationGlobals)

        const invocation = {
            id: new UUIDT().toString(),
            state: {
                event: invocationGlobals.event,
                actionStepCount: 0,
                variables: defaultVariables,
            },
            teamId: hogFlow.team_id,
            functionId: hogFlow.id,
            parentRunId,
            hogFlow,
            person: invocationGlobals.person,
            filterGlobals,
            queue: 'hogflow' as const,
            queuePriority: 1,
        }
        return invocation
    }

    /**
     * Finds all matching persons for the given globals.
     * Filters them based on the hogflow's masking configs
     */
    @instrumented('cdpProducer.generateBatch.queueMatchingPersons')
    protected async createHogFlowInvocations(
        batchHogFlowRequestMessage: BatchHogFlowRequestMessage
    ): Promise<CyclotronJobInvocation[]> {
        const { batchHogFlowRequest, team, hogFlow } = batchHogFlowRequestMessage
        const { filters } = batchHogFlowRequest

        if (!filters.properties || !filters.properties.length) {
            logger.error('Batch HogFlow request missing property filters', { batchHogFlowRequest })
            return []
        }

        // Build default variables from hogFlow
        const defaultVariables =
            hogFlow.variables?.reduce(
                (acc, variable) => {
                    acc[variable.key] = variable.default || null
                    return acc
                },
                {} as Record<string, any>
            ) || {}

        const allInvocations: CyclotronJobInvocation[] = []
        let cursor: string | null = null
        let totalPersonsProcessed = 0

        // Fetch persons in batches using cursor-based pagination
        do {
            const blastRadiusPersons = await instrumentFn(
                'cdpProducer.generateBatch.queueMatchingPersons.getBlastRadiusPersons',
                async () => {
                    return await this.hogFlowBatchPersonQueryService.getBlastRadiusPersons(
                        team,
                        filters,
                        batchHogFlowRequest.group_type_index,
                        cursor
                    )
                }
            )

            const batchPersonsCount = blastRadiusPersons.users_affected.length
            totalPersonsProcessed += batchPersonsCount

            logger.info(
                '📝',
                `Fetched ${batchPersonsCount} persons (${totalPersonsProcessed} total) for batch HogFlow run ${batchHogFlowRequest.parentRunId}`
            )

            // Create invocations for this batch of persons
            const batchInvocations = blastRadiusPersons.users_affected.map((personId) =>
                this.createHogFlowInvocation({
                    parentRunId: batchHogFlowRequest.parentRunId,
                    hogFlow,
                    team,
                    personId,
                    defaultVariables,
                })
            )

            allInvocations.push(...batchInvocations)

            // Update cursor for next iteration
            cursor = blastRadiusPersons.cursor

            // Continue if there are more persons to fetch
            if (!blastRadiusPersons.has_more) {
                break
            }
        } while (cursor)

        logger.info(
            '✅',
            `Created ${allInvocations.length} invocations for batch HogFlow run ${batchHogFlowRequest.parentRunId}`
        )

        return allInvocations
    }

    private async processBatchHogFlowRequest(
        batchHogFlowRequests: BatchHogFlowRequestMessage[]
    ): Promise<{ backgroundTask: Promise<any>; invocations: CyclotronJobInvocation[] }> {
        if (batchHogFlowRequests.length > 1) {
            logger.warn(
                '🔁',
                `Processing multiple ${batchHogFlowRequests.length} hog flow requests. This is NOT recommended due to potential fanout. Batch size is set by CDP_BATCH_WORKFLOW_PRODUCER_BATCH_SIZE`
            )
        }

        const invocationsToBeQueued = [
            ...(
                await Promise.all(batchHogFlowRequests.map((request) => this.createHogFlowInvocations(request)))
            ).flat(),
        ]

        logger.info('📝', `Created ${invocationsToBeQueued.length} hog flow invocations to be queued`)

        return {
            // This is all IO so we can set them off in the background and start processing the next batch
            backgroundTask: Promise.all([
                this.cyclotronJobQueue.queueInvocations(invocationsToBeQueued),
                this.hogFunctionMonitoringService.flush().catch((err) => {
                    captureException(err)
                    logger.error('🔴', 'Error producing queued messages for monitoring', { err })
                }),
            ]),
            invocations: invocationsToBeQueued,
        }
    }

    private async processBatch(
        batchHogFlowRequests: BatchHogFlowRequestMessage[]
    ): Promise<{ backgroundTask: Promise<any>; invocations: CyclotronJobInvocation[] }> {
        if (!batchHogFlowRequests.length) {
            return { backgroundTask: Promise.resolve(), invocations: [] }
        }

        return await instrumentFn('cdpConsumer.processBatchHogFlowRequest', async () => {
            return await this.processBatchHogFlowRequest(batchHogFlowRequests)
        })
    }

    @instrumented('cdpConsumer.handleEachBatch.parseKafkaMessages')
    public async _parseKafkaBatch(messages: Message[]): Promise<BatchHogFlowRequestMessage[]> {
        const batchHogFlowRequests: BatchHogFlowRequestMessage[] = []

        await Promise.all(
            messages.map(async (message) => {
                try {
                    const batchHogFlowRequest = parseJSON(message.value!.toString()) as BatchHogFlowRequest

                    const [teamHogFlow, team] = await Promise.all([
                        this.hogFlowManager.getHogFlow(batchHogFlowRequest.hogFlowId),
                        this.deps.teamManager.getTeam(batchHogFlowRequest.teamId),
                    ])

                    if (!teamHogFlow || !team) {
                        logger.error('Batch HogFlow request references missing team or hogflow', {
                            batchHogFlowRequest,
                        })
                        return
                    }

                    if (teamHogFlow.status !== 'active') {
                        logger.info('Skipping inactive HogFlow for batch request', { batchHogFlowRequest })
                        return
                    }

                    batchHogFlowRequests.push({
                        batchHogFlowRequest,
                        team,
                        hogFlow: teamHogFlow,
                    })
                } catch (e) {
                    logger.error('Error parsing message', e)
                    counterParseError.labels({ error: e.message }).inc()
                }
            })
        )

        return batchHogFlowRequests
    }

    public async start(): Promise<void> {
        await super.start()
        // Make sure we are ready to produce to cyclotron first
        await this.cyclotronJobQueue.startAsProducer()
        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await instrumentFn('cdpConsumer.handleEachBatch', async () => {
                const batchHogFlowRequestMessages = await this._parseKafkaBatch(messages)
                const { backgroundTask } = await this.processBatch(batchHogFlowRequestMessages)

                return { backgroundTask }
            })
        })
    }

    public async stop(): Promise<void> {
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
