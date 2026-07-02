import { Message } from 'node-rdkafka'

import { HogFlow } from '~/cdp/schema/hogflow'
import { KAFKA_CDP_BATCH_HOGFLOW_REQUESTS } from '~/common/config/kafka-topics'
import { KafkaConsumerInterface, createKafkaConsumer } from '~/common/kafka/consumer'
import { InternalFetchService } from '~/common/services/internal-fetch'
import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger, serializeError } from '~/common/utils/logger'
import { captureException } from '~/common/utils/posthog'
import { UUIDT } from '~/common/utils/utils'

import { HealthCheckResult, PluginsServerConfig, Team } from '../../types'
import { HogFlowBatchPersonQueryService } from '../services/hogflows/hogflow-batch-person-query.service'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { CyclotronJobInvocation, HogFunctionFilters } from '../types'
import { convertBatchHogFlowRequestToHogFunctionInvocationGlobals, logEntry } from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'
import { counterBatchHogFlowTriggerFailed, counterParseError } from './metrics'

export interface BatchHogFlowRequest {
    teamId: number
    hogFlowId: HogFlow['id']
    parentRunId: string
    filters: Pick<HogFunctionFilters, 'properties' | 'filter_test_accounts'>
    group_type_index?: number
    // Per-team audience cap resolved on the Django side (HOGFLOW_BATCH_TRIGGER_LIMIT). When absent,
    // we fall back to the global CDP_BATCH_WORKFLOW_MAX_AUDIENCE_SIZE config default.
    maxAudienceSize?: number
}

export interface BatchHogFlowRequestMessage {
    batchHogFlowRequest: BatchHogFlowRequest
    team: Team
    hogFlow: HogFlow
}

export class CdpBatchHogFlowRequestsConsumer extends CdpConsumerBase<PluginsServerConfig> {
    protected name = 'CdpBatchHogFlowRequestsConsumer'
    private cyclotronJobQueue: JobQueue
    protected kafkaConsumer: KafkaConsumerInterface
    private hogFlowBatchPersonQueryService: HogFlowBatchPersonQueryService

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        jobQueue: JobQueue,
        topic: string = KAFKA_CDP_BATCH_HOGFLOW_REQUESTS,
        groupId: string = 'cdp-batch-hogflow-requests-consumer'
    ) {
        super(config, deps)
        this.cyclotronJobQueue = jobQueue
        this.kafkaConsumer = createKafkaConsumer({ groupId, topic })
        this.hogFlowBatchPersonQueryService = new HogFlowBatchPersonQueryService(
            new InternalFetchService(config.INTERNAL_API_BASE_URL, config.INTERNAL_API_SECRET)
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
            personId,
            siteUrl: this.config.SITE_URL,
        })

        const filterGlobals = convertToHogFunctionFilterGlobal(invocationGlobals)

        const invocation = {
            id: new UUIDT().toString(),
            state: {
                event: invocationGlobals.event,
                personId,
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
            this.recordBatchTriggerFailure(
                batchHogFlowRequestMessage,
                'missing_filters',
                'Batch trigger has no property filters configured.'
            )
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
        const maxAudienceSize = batchHogFlowRequest.maxAudienceSize ?? this.config.CDP_BATCH_WORKFLOW_MAX_AUDIENCE_SIZE

        try {
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

                if (totalPersonsProcessed > maxAudienceSize) {
                    logger.warn(
                        '⚠️',
                        `Batch HogFlow run ${batchHogFlowRequest.parentRunId} has exceeded the maximum audience size of ${maxAudienceSize}. Stopping further processing.`,
                        { totalPersonsProcessed, batchHogFlowRequest }
                    )
                    break
                }

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
        } catch (error) {
            // Audience resolution failed (e.g. unsupported filter property like a feature flag in person scope).
            // Record a workflow-level failure so the run is observable in logs/metrics, then drop the batch
            // instead of crashing the consumer and re-processing the same poison message in a tight loop.
            const message = error instanceof Error ? error.message : String(error)
            logger.error('🔴', 'Failed to resolve audience for batch HogFlow run, skipping batch', {
                error: serializeError(error),
                hogFlowId: hogFlow.id,
                teamId: team.id,
                parentRunId: batchHogFlowRequest.parentRunId,
            })
            captureException(error, {
                tags: { hogFlowId: hogFlow.id, parentRunId: batchHogFlowRequest.parentRunId },
            })
            this.recordBatchTriggerFailure(
                batchHogFlowRequestMessage,
                'audience_query_failed',
                `Failed to resolve batch audience: ${message}`
            )
            return []
        }

        logger.info(
            '✅',
            `Created ${allInvocations.length} invocations for batch HogFlow run ${batchHogFlowRequest.parentRunId}`
        )

        return allInvocations
    }

    private recordBatchTriggerFailure(
        batchHogFlowRequestMessage: BatchHogFlowRequestMessage,
        reason: 'missing_filters' | 'audience_query_failed',
        userMessage: string
    ): void {
        const { batchHogFlowRequest, hogFlow } = batchHogFlowRequestMessage

        counterBatchHogFlowTriggerFailed.labels({ hog_flow_id: hogFlow.id, reason }).inc()

        this.hogFunctionMonitoringService.queueAppMetric(
            {
                team_id: hogFlow.team_id,
                app_source_id: hogFlow.id,
                instance_id: batchHogFlowRequest.parentRunId,
                metric_kind: 'failure',
                metric_name: 'trigger_failed',
                count: 1,
            },
            'hog_flow'
        )

        this.hogFunctionMonitoringService.queueLogs(
            [
                {
                    team_id: hogFlow.team_id,
                    log_source: 'hog_flow',
                    log_source_id: batchHogFlowRequest.parentRunId,
                    instance_id: batchHogFlowRequest.parentRunId,
                    ...logEntry('error', userMessage),
                },
            ],
            'hog_flow'
        )
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
                const batchHogFlowRequestMessages = await this._parseKafkaBatch(messages)
                const { backgroundTask } = await this.processBatch(batchHogFlowRequestMessages)

                return { backgroundTask }
            })
        })
    }

    public override async stop(): Promise<void> {
        logger.info('💤', 'Stopping consumer...')
        await this.kafkaConsumer.disconnect()
        logger.info('💤', 'Stopping cyclotron job queue...')
        await this.cyclotronJobQueue.stopProducer()
        logger.info('💤', 'Stopping consumer...')
        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.kafkaConsumer.isHealthy()
    }
}
