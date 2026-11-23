import { Counter } from 'prom-client'

import { getExternalRequestConfig } from '~/common/config'
import { RedisV2 } from '~/common/redis/redis-v2'

export type ConnectionRateLimiterOptions = {
    perSecond: number
    burst: number
    // A slow Redis must not hold up new connections, so past this every connection goes through.
    redisDeadlineMs?: number
}

const unavailableCounter = new Counter({
    name: 'node_request_connection_rate_limiter_unavailable_total',
    help: 'New connections let through without a limit check because Redis did not answer in time',
})

// Each new connection holds one of ~55,000 NAT ports per destination IP for a while after it closes. The budget lives
// in Redis because a per-pod budget grows with the pod count and the NAT's ports do not.
export class ConnectionRateLimiter {
    constructor(
        private readonly redis: RedisV2,
        private readonly options: ConnectionRateLimiterOptions
    ) {}

    async tryTake(keys: string[]): Promise<boolean[]> {
        const { perSecond, burst, redisDeadlineMs = 50 } = this.options
        const now = Math.round(Date.now() / 1000)
        const ttlSeconds = Math.ceil(burst / perSecond) + 60
        // failOpen does not cover a pool that cannot hand out a client in time, so that error is caught here.
        const res = await this.redis
            .usePipeline(
                { name: 'connection-rate-limiter', failOpen: true, deadlineMs: redisDeadlineMs },
                (pipeline) => {
                    for (const key of keys) {
                        pipeline.checkRateLimitV2(
                            `@posthog/new-connections/${key}`,
                            now,
                            1,
                            burst,
                            perSecond,
                            ttlSeconds
                        )
                    }
                }
            )
            .catch(() => null)
        // The script returns -1 when the bucket could not pay, and 0 when it paid its last token.
        return keys.map((_, index) => {
            const [error, result] = res?.[index] ?? [null, null]
            if (error !== null || result === null) {
                unavailableCounter.inc()
                return true
            }
            return Number(result[1]) >= 0
        })
    }
}

let installed: ConnectionRateLimiter | null = null

// Lives here rather than in request.ts, which many tests mock whole, so CDP startup can call it under those mocks.
export function limitNewConnectionsWith(redis: RedisV2 | null, redisDeadlineMs?: number): void {
    const config = getExternalRequestConfig()
    const perSecond = config.EXTERNAL_REQUEST_NEW_CONNECTIONS_PER_IP_PER_SECOND
    installed =
        redis && perSecond > 0
            ? new ConnectionRateLimiter(redis, {
                  perSecond,
                  burst: config.EXTERNAL_REQUEST_NEW_CONNECTIONS_PER_IP_BURST,
                  redisDeadlineMs,
              })
            : null
}

export function installedConnectionRateLimiter(): ConnectionRateLimiter | null {
    return installed
}
