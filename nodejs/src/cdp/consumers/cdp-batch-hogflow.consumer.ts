import { Message } from 'node-rdkafka'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { KAFKA_CDP_BATCH_HOGFLOW_REQUESTS } from '~/config/kafka-topics'
import { HogFlow } from '~/schema/hogflow'
import { parseJSON } from '~/utils/json-parse'
import { captureException } from '~/utils/posthog'

import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub, PersonPropertyFilter, Team } from '../../types'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogRateLimiterService } from '../services/monitoring/hog-rate-limiter.service'
import { CyclotronJobInvocation, HogFunctionFilters } from '../types'
import { convertBatchHogFlowRequestToHogFunctionInvocationGlobals } from '../utils'
import { convertToHogFunctionFilterGlobal } from '../utils/hog-function-filtering'
import { CdpConsumerBase } from './cdp-base.consumer'
import { counterParseError } from './metrics'

export interface BatchHogFlowRequest {
    teamId: number
    hogFlowId: HogFlow['id']
    parentRunId: string
    filters: Pick<HogFunctionFilters, 'properties' | 'filter_test_accounts'>
}

export interface BatchHogFlowRequestMessage {
    batchHogFlowRequest: BatchHogFlowRequest
    team: Team
    hogFlow: HogFlow
}

export class CdpBatchHogFlowRequestsConsumer extends CdpConsumerBase {
    protected name = 'CdpBatchHogFlowRequestsConsumer'
    private cyclotronJobQueue: CyclotronJobQueue
    protected kafkaConsumer: KafkaConsumer

    private hogRateLimiter: HogRateLimiterService

    constructor(
        hub: Hub,
        topic: string = KAFKA_CDP_BATCH_HOGFLOW_REQUESTS,
        groupId: string = 'cdp-batch-hogflow-requests-consumer'
    ) {
        super(hub)
        this.cyclotronJobQueue = new CyclotronJobQueue(hub, 'hogflow')
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
        this.hogRateLimiter = new HogRateLimiterService(hub, this.redis)
    }

    private createHogFlowInvocation({
        parentRunId,
        hogFlow,
        team,
        personId,
        distinctId,
        defaultVariables,
    }: {
        parentRunId: string
        hogFlow: HogFlow
        team: Team
        personId: string
        distinctId: string
        defaultVariables: Record<string, any>
    }): CyclotronJobInvocation {
        const invocationGlobals = convertBatchHogFlowRequestToHogFunctionInvocationGlobals({
            team: team,
            personId: personId,
            distinctId: distinctId,
            siteUrl: this.hub.SITE_URL,
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

        const matchingPersonsCount = await instrumentFn(
            'cdpProducer.generateBatch.queueMatchingPersons.matchingPersonsCount',
            async () => {
                return await this.personsManager.countMany({
                    teamId: team.id,
                    properties: (filters.properties as PersonPropertyFilter[]) || [],
                })
            }
        )

        logger.info(
            '📝',
            `Found ${matchingPersonsCount} matching persons for batch HogFlow run ${batchHogFlowRequest.parentRunId}`
        )

        // Build default variables from hogFlow
        const defaultVariables =
            hogFlow.variables?.reduce(
                (acc, variable) => {
                    acc[variable.key] = variable.default || null
                    return acc
                },
                {} as Record<string, any>
            ) || {}

        const invocations: CyclotronJobInvocation[] = []
        await instrumentFn('cdpProducer.generateBatch.queueMatchingPersons.paginatePersons', async () => {
            await this.personsManager.streamMany({
                filters: {
                    teamId: team.id,
                    properties: (filters.properties as PersonPropertyFilter[]) || [],
                },
                onPersonBatch: async (persons: { personId: string; distinctId: string }[]) => {
                    const batchInvocations = persons.map(({ personId, distinctId }) =>
                        this.createHogFlowInvocation({
                            parentRunId: batchHogFlowRequest.parentRunId,
                            hogFlow,
                            team,
                            personId,
                            distinctId,
                            defaultVariables,
                        })
                    )

                    invocations.push(...batchInvocations)
                    return Promise.resolve()
                },
            })
        })

        return invocations
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
                        this.hub.teamManager.getTeam(batchHogFlowRequest.teamId),
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
