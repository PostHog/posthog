import { Counter, Gauge } from 'prom-client'

import { KeyedRateLimiterService } from '~/common/services/keyed-rate-limiter.service'

import { RedisV2 } from '../../../common/redis/redis-v2'

export const EMAIL_RATE_LIMITER_NAME = 'cdp-email'
export const EMAIL_RATE_LIMITER_KEY = 'global-email'

const tokensAvailable = new Gauge({
    name: 'cdp_email_rate_limit_tokens_available',
    help: 'Tokens available in the global email rate limit bucket after the most recent decision.',
})
const deferredTotal = new Counter({
    name: 'cdp_email_rate_limited_total',
    help: 'Emails deferred by the global SES rate limiter.',
})

export interface EmailRateLimiterConfig {
    bucketSize: number
    refillRate: number
    /** TTL on the bucket key — sized longer than any plausible quiet window so accrued credit survives. */
    ttlSeconds?: number
}

export interface EmailRateLimitDecision {
    /** Number of invocations that may be processed now. */
    processCount: number
    /** Number of invocations that must be deferred. */
    deferCount: number
    /** Approximate tokens remaining after the consume. Used only for the gauge. */
    tokensAfter: number
}

/**
 * Global SES rate limiter shared across all email workers. Wraps a
 * `KeyedRateLimiterService` against a dedicated Valkey instance so the email
 * limiter is isolated from CDP's main Redis (which is CPU-bound).
 *
 * The underlying Lua (`checkRateLimitV2`) is all-or-nothing: cost > available
 * returns `tokensAfter = -1` and does not consume anything. To preserve the
 * old PR's partial-batch semantics atomically across workers, we issue a
 * second call requesting exactly `floor(tokensBefore)` when the first is
 * denied. Worst case is 2 round trips per batch under sustained overload.
 */
export class EmailRateLimiterService {
    private readonly limiter: KeyedRateLimiterService

    constructor(
        private readonly config: EmailRateLimiterConfig,
        redis: RedisV2
    ) {
        this.limiter = new KeyedRateLimiterService(
            {
                name: EMAIL_RATE_LIMITER_NAME,
                bucketSize: config.bucketSize,
                refillRate: config.refillRate,
                ttlSeconds: config.ttlSeconds ?? 60 * 60 * 24,
                // Surface the underlying pipeline failure so the caller can decide whether
                // to fail open (current behavior in the email consumer). Fail-open at this
                // layer would silently mask Valkey outages.
                failOpen: false,
            },
            redis
        )
    }

    public async decide(batchSize: number): Promise<EmailRateLimitDecision> {
        if (batchSize <= 0) {
            return { processCount: 0, deferCount: 0, tokensAfter: this.config.bucketSize }
        }

        // First call: try to consume the whole batch atomically.
        const [[, full]] = await this.limiter.rateLimitMany([{ id: EMAIL_RATE_LIMITER_KEY, cost: batchSize }])

        if (!full.isRateLimited) {
            tokensAvailable.set(Math.max(0, Math.floor(full.tokens)))
            return { processCount: batchSize, deferCount: 0, tokensAfter: full.tokens }
        }

        // Denied: tokensBefore tells us what was available. Consume floor() of that
        // in a second atomic call so two workers can't both observe the same budget.
        const available = Math.max(0, Math.floor(full.tokensBefore))
        if (available === 0) {
            tokensAvailable.set(0)
            deferredTotal.inc(batchSize)
            return { processCount: 0, deferCount: batchSize, tokensAfter: full.tokensBefore }
        }

        const [[, partial]] = await this.limiter.rateLimitMany([{ id: EMAIL_RATE_LIMITER_KEY, cost: available }])

        // Even the partial can be denied if a competing worker drained the bucket
        // between our two calls — defer the whole batch in that case.
        if (partial.isRateLimited) {
            tokensAvailable.set(Math.max(0, Math.floor(partial.tokensBefore)))
            deferredTotal.inc(batchSize)
            return { processCount: 0, deferCount: batchSize, tokensAfter: partial.tokensBefore }
        }

        tokensAvailable.set(Math.max(0, Math.floor(partial.tokens)))
        const deferCount = batchSize - available
        deferredTotal.inc(deferCount)
        return { processCount: available, deferCount, tokensAfter: partial.tokens }
    }
}
