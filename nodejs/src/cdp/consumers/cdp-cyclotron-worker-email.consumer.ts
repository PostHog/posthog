import { DateTime } from 'luxon'
import { Counter, Gauge } from 'prom-client'

import { PluginsServerConfig } from '~/types'

import { logger } from '../../utils/logger'
import { HogRateLimiterService } from '../services/monitoring/hog-rate-limiter.service'
import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import { CdpConsumerBaseDeps } from './cdp-base.consumer'
import { CdpCyclotronWorkerHogFlow } from './cdp-cyclotron-worker-hogflow.consumer'

const emailRateLimitedTotal = new Counter({
    name: 'cdp_email_rate_limited_total',
    help: 'Total emails deferred by rate limiting',
    labelNames: ['scope'],
})

const emailRateLimitTokensAvailable = new Gauge({
    name: 'cdp_email_rate_limit_tokens_available',
    help: 'Available tokens in rate limit buckets',
    labelNames: ['scope'],
})

const RATE_LIMIT_RETRY_BASE_MS = 500
const RATE_LIMIT_JITTER_MS = 200

export class CdpCyclotronWorkerEmail extends CdpCyclotronWorkerHogFlow {
    protected override name = 'CdpCyclotronWorkerEmail'
    private globalRateLimiter: HogRateLimiterService | null = null
    private perTeamRateLimiter: HogRateLimiterService | null = null

    constructor(config: PluginsServerConfig, deps: CdpConsumerBaseDeps) {
        super(config, deps)
        this.queue = 'email'

        if (config.CDP_EMAIL_GLOBAL_RATE_LIMIT_BUCKET_SIZE > 0 && config.CDP_EMAIL_GLOBAL_RATE_LIMIT_REFILL_RATE > 0) {
            this.globalRateLimiter = new HogRateLimiterService(
                {
                    bucketSize: config.CDP_EMAIL_GLOBAL_RATE_LIMIT_BUCKET_SIZE,
                    refillRate: config.CDP_EMAIL_GLOBAL_RATE_LIMIT_REFILL_RATE,
                    ttl: 60 * 60 * 24,
                },
                this.redis
            )
        }

        if (
            config.CDP_EMAIL_PER_TEAM_RATE_LIMIT_BUCKET_SIZE > 0 &&
            config.CDP_EMAIL_PER_TEAM_RATE_LIMIT_REFILL_RATE > 0
        ) {
            this.perTeamRateLimiter = new HogRateLimiterService(
                {
                    bucketSize: config.CDP_EMAIL_PER_TEAM_RATE_LIMIT_BUCKET_SIZE,
                    refillRate: config.CDP_EMAIL_PER_TEAM_RATE_LIMIT_REFILL_RATE,
                    ttl: 60 * 60 * 24,
                },
                this.redis
            )
        }
    }

    public override async start() {
        const consumerMode = this.config.CYCLOTRON_NODE_DATABASE_URL ? 'postgres-v2' : undefined
        await super.start(consumerMode)
    }

    public override async processInvocations(
        invocations: CyclotronJobInvocation[]
    ): Promise<CyclotronJobInvocationResult[]> {
        if (invocations.length === 0) {
            return super.processInvocations(invocations)
        }

        if (!this.globalRateLimiter && !this.perTeamRateLimiter) {
            return super.processInvocations(invocations)
        }

        let toProcess = invocations
        let toDefer: CyclotronJobInvocation[] = []

        try {
            // Step 1: Global rate limit
            if (this.globalRateLimiter) {
                const [[, rateLimit]] = await this.globalRateLimiter.rateLimitMany([
                    ['global-email', toProcess.length],
                ])
                const overConsumed = Math.max(0, -Math.floor(rateLimit.tokens))
                emailRateLimitTokensAvailable.labels({ scope: 'global' }).set(Math.max(0, Math.floor(rateLimit.tokens)))

                if (overConsumed > 0) {
                    toDefer = toProcess.slice(toProcess.length - overConsumed)
                    toProcess = toProcess.slice(0, toProcess.length - overConsumed)
                }
            }

            // Step 2: Per-team rate limit on the remaining invocations
            if (this.perTeamRateLimiter && toProcess.length > 0) {
                const byTeam = new Map<number, CyclotronJobInvocation[]>()
                for (const inv of toProcess) {
                    const list = byTeam.get(inv.teamId) ?? []
                    list.push(inv)
                    byTeam.set(inv.teamId, list)
                }

                const teamCosts: [string, number][] = Array.from(byTeam.entries()).map(([teamId, invs]) => [
                    `team-email:${teamId}`,
                    invs.length,
                ])

                const teamResults = await this.perTeamRateLimiter.rateLimitMany(teamCosts)

                const teamProcessed: CyclotronJobInvocation[] = []
                let teamIdx = 0
                for (const [teamId, teamInvocations] of byTeam.entries()) {
                    const [, teamRateLimit] = teamResults[teamIdx]
                    const teamOverConsumed = Math.max(0, -Math.floor(teamRateLimit.tokens))

                    emailRateLimitTokensAvailable
                        .labels({ scope: `team:${teamId}` })
                        .set(Math.max(0, Math.floor(teamRateLimit.tokens)))

                    if (teamOverConsumed > 0) {
                        teamProcessed.push(...teamInvocations.slice(0, teamInvocations.length - teamOverConsumed))
                        toDefer.push(...teamInvocations.slice(teamInvocations.length - teamOverConsumed))
                    } else {
                        teamProcessed.push(...teamInvocations)
                    }
                    teamIdx++
                }

                toProcess = teamProcessed
            }
        } catch (err) {
            logger.error('Email rate limiter failed, processing batch without rate limiting', { error: String(err) })
            return super.processInvocations(invocations)
        }

        if (toDefer.length === 0) {
            return super.processInvocations(invocations)
        }

        logger.info('Email rate limit applied', {
            batchSize: invocations.length,
            processing: toProcess.length,
            deferred: toDefer.length,
        })

        const results = toProcess.length > 0 ? await super.processInvocations(toProcess) : []

        for (let i = 0; i < toDefer.length; i++) {
            const jitterMs = Math.floor(Math.random() * RATE_LIMIT_JITTER_MS)
            const delayMs = RATE_LIMIT_RETRY_BASE_MS + jitterMs
            results.push(
                createInvocationResult(
                    toDefer[i],
                    { queueScheduledAt: DateTime.now().plus({ milliseconds: delayMs }) },
                    { finished: false }
                )
            )
            emailRateLimitedTotal.labels({ scope: toDefer[i].teamId === invocations[0]?.teamId ? 'team' : 'global' }).inc()
        }

        return results
    }
}
