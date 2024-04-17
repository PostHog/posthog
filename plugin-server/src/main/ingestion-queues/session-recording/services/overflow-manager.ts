import { Redis } from 'ioredis'
import LRUCache from 'lru-cache'
import { Gauge } from 'prom-client'

import { status } from '../../../../utils/status'
import { Limiter } from '../../../../utils/token-bucket'

export const overflowTriggeredGauge = new Gauge({
    name: 'overflow_detection_triggered_total',
    help: 'Number of entities that triggered overflow detection.',
})

/**
 * OverflowManager handles consumer-side detection of hot partitions by
 * accounting for data volumes per entity (a session_id, a distinct_id...)
 * and maintains the Redis set that capture reads to route messages.
 *
 * The first time that the observed spike crosses the thresholds set via burstCapacity
 * and replenishRate, the key is added to Redis and the metrics incremented, subsequent
 * calls will return early until cooldownSeconds is reached.
 */
export class OverflowManager {
    private limiter: Limiter
    private triggered: LRUCache<string, boolean>

    constructor(
        burstCapacity: number,
        replenishRate: number,
        private minPerCall: number,
        private cooldownSeconds: number,
        private redisKey: string,
        private redisClient: Redis
    ) {
        this.limiter = new Limiter(burstCapacity, replenishRate)
        this.triggered = new LRUCache({ max: 1_000_000, maxAge: cooldownSeconds * 1000 })
        status.info('🚛 ', '[overflow-manager] manager stated', {
            redis_key: this.redisKey,
            burstCapacity,
            replenishRate,
        })
    }

    public async observe(key: string, quantity: number, now?: number): Promise<void> {
        if (this.triggered.has(key)) {
            // Cooldown state, return early
            return
        }
        if (this.limiter.consume(key, Math.max(this.minPerCall, quantity), now)) {
            // Not triggering overflow, return early
            return
        }
        this.triggered.set(key, true)
        overflowTriggeredGauge.inc(1)

        // Set the `NX` arguments to not update existing entries: if a session already triggered overflow,
        // it's cooldown will not be extended after we restart the consumers.
        // The zset value is a timestamp in seconds.
        const expiration = (now ?? Date.now()) / 1000 + this.cooldownSeconds
        await this.redisClient.zadd(this.redisKey, 'NX', expiration, key)
        status.info('🚛 ', '[overflow-manager] added new overflow record', {
            redis_key: this.redisKey,
            key,
            expiration,
        })

        // Cleanup old entries with values expired more than one hour ago.
        // We run the cleanup here because we assume this will only run a dozen times per day per region.
        // If this code path becomes too hot, it should move to a singleton loop.
        const expired = (now ?? Date.now()) / 1000 - 3600
        await this.redisClient.zremrangebyscore(this.redisKey, 0, expired)
    }
}
