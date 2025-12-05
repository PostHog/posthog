import { Message } from 'node-rdkafka'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { KAFKA_CDP_BATCH_HOGFLOW_REQUESTS } from '~/config/kafka-topics'
import { HogFlow } from '~/schema/hogflow'
import { parseJSON } from '~/utils/json-parse'
import { captureException } from '~/utils/posthog'

import { KafkaConsumer } from '../../kafka/consumer'
import { HealthCheckResult, Hub, Team } from '../../types'
import { logger } from '../../utils/logger'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogRateLimiterService } from '../services/monitoring/hog-rate-limiter.service'
import { CyclotronJobInvocation, HogFunctionFilters, HogFunctionTypeType } from '../types'
import { convertBatchHogFlowRequestToHogFunctionInvocationGlobals } from '../utils'
import { CdpConsumerBase } from './cdp-base.consumer'
import { counterParseError, counterRateLimited } from './cdp-events.consumer'

export interface BatchHogFlowRequest {
    teamId: number
    hogFlowId: HogFlow['id']
    filters: Pick<HogFunctionFilters, 'properties' | 'filter_test_accounts'>
}

export interface BatchHogFlowRequestMessage {
    batchHogFlowRequest: BatchHogFlowRequest
    team: Team
    hogFlow: HogFlow
}

export class CdpBatchHogFlowRequestsConsumer extends CdpConsumerBase {
    protected name = 'CdpBatchHogFlowRequestConsumer'
    protected hogTypes: HogFunctionTypeType[] = ['destination']
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

    /**
     * Finds all matching persons for the given globals.
     * Filters them based on the hogflow's masking configs
     */
    @instrumented('cdpProducer.generateBatch.queueMatchingPersons')
    protected async createHogFlowInvocations(
        batchHogFlowRequest: BatchHogFlowRequestMessage
    ): Promise<CyclotronJobInvocation[]> {
        const matchingPersonsCount = await instrumentFn(
            'cdpProducer.generateBatch.queueMatchingPersons.matchingPersonsCount',
            async () => {
                return await this.personsManager.getMany(batchFilters)
            }
        )

        const rateLimits = await instrumentFn('cdpProducer.generateBatch.hogRateLimiter.rateLimitMany', async () => {
            return await this.hogRateLimiter.rateLimitMany([batchHogFlowRequest.hogFlow.id, matchingPersonsCount])
        })

        const rateLimit = rateLimits[0][1]
        if (rateLimit.isRateLimited) {
            counterRateLimited.labels({ kind: 'hog_flow' }).inc()
            this.hogFunctionMonitoringService.queueAppMetric(
                {
                    team_id: batchHogFlowRequest.team.id,
                    app_source_id: batchHogFlowRequest.hogFlow.id,
                    metric_kind: 'failure',
                    metric_name: 'rate_limited',
                    count: 1,
                },
                'hog_flow'
            )
            return []
        }

        // Get all persons using stream pagination
        const invocations: CyclotronJobInvocation[] = []
        await instrumentFn('cdpProducer.generateBatch.queueMatchingPersons.paginatePersons', async () => {
            for await (const person of this.personsManager.paginateMany(batchFilters)) {
                const invocationGlobals = convertBatchHogFlowRequestToHogFunctionInvocationGlobals({
                    team: person.team,
                    personId: person.id,
                    distinctId: person.distinct_ids[0],
                    siteUrl: this.hub.SITE_URL,
                })

                invocations.push({
                    //    todo
                })
            }
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
            ...(await Promise.all(batchHogFlowRequests.map(this.createHogFlowInvocations))).flat(),
        ]

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
        logger.info('💤', 'Stopping cyclotron job queue...')
        await this.cyclotronJobQueue.stop()
        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Consumer stopped!')
    }

    public isHealthy(): HealthCheckResult {
        return this.cyclotronJobQueue.isHealthy()
    }
}
