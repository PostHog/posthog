import { Counter } from 'prom-client'

import { instrumentFn, instrumented } from '~/common/tracing/tracing-utils'
import { HogFlow } from '~/schema/hogflow'

import { HealthCheckResult, Hub } from '../../types'
import { logger } from '../../utils/logger'
import { CyclotronJobQueue } from '../services/job-queue/job-queue'
import { HogRateLimiterService } from '../services/monitoring/hog-rate-limiter.service'
import { CyclotronJobInvocation, HogFunctionFilters, HogFunctionTypeType } from '../types'
import { CdpProducerBase } from './cdp-base.producer'

const counterRateLimited = new Counter({
    name: 'cdp_function_rate_limited',
    help: 'A function invocation was rate limited',
    labelNames: ['kind'],
})

export class CdpCyclotronProducerBatch extends CdpProducerBase {
    protected name = 'CdpCyclotronProducerBatch'
    protected hogTypes: HogFunctionTypeType[] = ['destination']
    private cyclotronJobQueue: CyclotronJobQueue

    private hogRateLimiter: HogRateLimiterService

    constructor(hub: Hub) {
        super(hub)
        this.cyclotronJobQueue = new CyclotronJobQueue(hub, 'hogflow')
        this.hogRateLimiter = new HogRateLimiterService(hub, this.redis)
    }

    /**
     * Finds all matching persons for the given globals.
     * Filters them based on the hogflow's masking configs
     */
    @instrumented('cdpProducer.generateBatch.queueMatchingPersons')
    protected async createHogFlowInvocations(
        hogFlowId: HogFlow['id'],
        batchFilters: HogFunctionFilters
    ): Promise<CyclotronJobInvocation[]> {
        const matchingPersonsCount = await instrumentFn(
            'cdpProducer.generateBatch.queueMatchingPersons.matchingPersonsCount',
            async () => {
                return await this.personsManager.getMany(batchFilters)
            }
        )

        const rateLimits = await instrumentFn('cdpProducer.generateBatch.hogRateLimiter.rateLimitMany', async () => {
            return await this.hogRateLimiter.rateLimitMany([hogFlowId, matchingPersonsCount])
        })

        const rateLimit = rateLimits[0][1]
        if (rateLimit.isRateLimited) {
            counterRateLimited.labels({ kind: 'hog_flow' }).inc()
            this.hogFunctionMonitoringService.queueAppMetric(
                {
                    team_id: item.teamId,
                    app_source_id: item.functionId,
                    metric_kind: 'failure',
                    metric_name: 'rate_limited',
                    count: 1,
                },
                'hog_flow'
            )
            return
        }
    }

    public async start(): Promise<void> {
        await super.start()
        // Make sure we are ready to produce to cyclotron first
        await this.cyclotronJobQueue.startAsProducer()

        // TODO: spin up express server to handle incoming batch requests
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
