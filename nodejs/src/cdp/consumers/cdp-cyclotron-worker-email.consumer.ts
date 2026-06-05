import { DateTime } from 'luxon'

import { RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { PluginsServerConfig } from '~/types'

import { logger } from '../../utils/logger'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { EmailRateLimiterService } from '../services/messaging/email-rate-limiter.service'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

export class CdpCyclotronWorkerEmail extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerEmail'
    private emailRateLimiter: EmailRateLimiterService | null = null
    private emailValkey: RedisV2 | null = null
    private rateLimitRetryBaseMs: number
    private rateLimitJitterMs: number

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps, jobQueue: JobQueue) {
        super(config, deps, jobQueue)
        this.queue = 'email'

        this.rateLimitRetryBaseMs = config.CDP_EMAIL_RATE_LIMIT_RETRY_BASE_MS
        this.rateLimitJitterMs = config.CDP_EMAIL_RATE_LIMIT_JITTER_MS

        const bucketSize = config.CDP_EMAIL_RATE_LIMIT_BUCKET_SIZE
        const refillRate = config.CDP_EMAIL_RATE_LIMIT_REFILL_RATE

        // All three knobs must be set; missing host means there's no isolated
        // Valkey to talk to, which is the whole point of this limiter.
        if (config.CDP_EMAIL_VALKEY_HOST && bucketSize > 0 && refillRate > 0) {
            this.emailValkey = createRedisV2PoolFromConfig({
                connection: {
                    url: config.CDP_EMAIL_VALKEY_HOST,
                    options: {
                        port: config.CDP_EMAIL_VALKEY_PORT,
                        password: config.CDP_EMAIL_VALKEY_PASSWORD,
                        tls: config.CDP_EMAIL_VALKEY_TLS ? {} : undefined,
                    },
                    name: 'cdp-email-valkey',
                },
                poolMinSize: config.REDIS_POOL_MIN_SIZE,
                poolMaxSize: config.REDIS_POOL_MAX_SIZE,
            })

            this.emailRateLimiter = new EmailRateLimiterService({ bucketSize, refillRate }, this.emailValkey)

            logger.info(
                '✉️ ',
                `[CdpCyclotronWorkerEmail] rate limiter enabled bucket=${bucketSize} refill=${refillRate}/s valkey=${config.CDP_EMAIL_VALKEY_HOST}:${config.CDP_EMAIL_VALKEY_PORT}`
            )
        }
    }

    public override async stop(): Promise<void> {
        await super.stop()
        if (this.emailValkey?.destroy) {
            try {
                await this.emailValkey.destroy()
            } catch (err) {
                logger.warn('✉️ ', '[CdpCyclotronWorkerEmail] failed to drain email Valkey pool on stop', {
                    error: String(err),
                })
            }
        }
        this.emailValkey = null
        this.emailRateLimiter = null
    }

    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        if (!this.emailRateLimiter || invocations.length === 0) {
            return super.processInvocations(invocations)
        }

        let decision
        try {
            decision = await this.emailRateLimiter.decide(invocations.length)
        } catch (err) {
            // Valkey unreachable / pipeline failure → fail open so a single bad node
            // doesn't stall email delivery. Capacity protection regresses to "none"
            // for the duration of the outage; alert on cdp_email_rate_limit_*.
            logger.error('✉️ ', '[CdpCyclotronWorkerEmail] email rate limiter unavailable, processing batch', {
                error: String(err),
            })
            return super.processInvocations(invocations)
        }

        if (decision.deferCount === 0) {
            return super.processInvocations(invocations)
        }

        const toProcess = invocations.slice(0, decision.processCount)
        const toDefer = invocations.slice(decision.processCount)

        logger.info('✉️ ', '[CdpCyclotronWorkerEmail] rate limit applied', {
            batchSize: invocations.length,
            processing: toProcess.length,
            deferred: toDefer.length,
        })

        const results = toProcess.length > 0 ? await super.processInvocations(toProcess) : []

        for (const invocation of toDefer) {
            const jitterMs = Math.floor(Math.random() * this.rateLimitJitterMs)
            const delayMs = this.rateLimitRetryBaseMs + jitterMs
            results.push(
                createInvocationResult(
                    invocation,
                    { queueScheduledAt: DateTime.now().plus({ milliseconds: delayMs }) },
                    { finished: false }
                )
            )
        }

        return results
    }
}
