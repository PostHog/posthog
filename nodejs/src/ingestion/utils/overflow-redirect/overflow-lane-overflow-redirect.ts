import { Redis } from 'ioredis'

import {
    overflowRedirectEventsTotal,
    overflowRedirectKeysTotal,
    overflowRedirectRedisLatency,
    overflowRedirectRedisOpsTotal,
} from './metrics'
import {
    BaseOverflowRedirectConfig,
    BaseOverflowRedirectService,
    OverflowEventBatch,
    OverflowType,
} from './overflow-redirect-service'

export type OverflowLaneOverflowRedirectConfig = BaseOverflowRedirectConfig

/**
 * Overflow lane implementation of overflow redirect.
 *
 * For each batch of events:
 * 1. Batch refresh TTL for all keys in Redis using GETEX (only if key exists)
 * 2. Return empty set (no redirects - events stay in overflow lane)
 *
 * Uses GETEX to atomically get and refresh TTL. This only refreshes TTL for
 * keys that already exist - it won't create new keys. This is important because
 * keys may be flagged by other mechanisms (e.g., billing limits, session overflow).
 *
 * Once events stop coming, the flag expires after TTL and future events will
 * be processed in the main lane again.
 */
export class OverflowLaneOverflowRedirect extends BaseOverflowRedirectService {
    constructor(config: OverflowLaneOverflowRedirectConfig) {
        super(config)
    }

    async handleEventBatch(type: OverflowType, batch: OverflowEventBatch[]): Promise<Set<string>> {
        // Refresh TTL for all keys in the batch
        if (batch.length > 0) {
            await this.batchRefreshTTL(type, batch)
        }

        // Record key-level metrics - all keys pass through (no redirects in overflow lane)
        overflowRedirectKeysTotal.labels(type, 'passed').inc(batch.length)

        // Record event-level metrics - sum up all event counts
        const totalEvents = batch.reduce((sum, event) => sum + event.eventCount, 0)
        overflowRedirectEventsTotal.labels(type, 'passed').inc(totalEvents)

        // Never redirect from overflow lane - return empty set
        return new Set()
    }

    /**
     * Batch refresh TTL for keys in Redis using pipeline of GETEX commands.
     * GETEX only refreshes TTL if the key exists - it won't create new keys.
     */
    private async batchRefreshTTL(type: OverflowType, events: OverflowEventBatch[]): Promise<void> {
        const startTime = performance.now()
        let succeeded = false

        await this.withRedisClient(
            'batchRefreshTTL',
            { type, count: events.length },
            async (client: Redis) => {
                const pipeline = client.pipeline()

                // Queue GETEX with EX for each event to refresh TTL (only if key exists)
                for (const event of events) {
                    const key = this.redisKey(type, event.key.token, event.key.distinctId)
                    pipeline.getex(key, 'EX', this.redisTTLSeconds)
                }

                await pipeline.exec()
                succeeded = true
                overflowRedirectRedisOpsTotal.labels('getex', 'success').inc()
            },
            undefined
        )

        // Record latency and error metrics
        const latencySeconds = (performance.now() - startTime) / 1000
        overflowRedirectRedisLatency.labels('getex').observe(latencySeconds)

        if (!succeeded) {
            overflowRedirectRedisOpsTotal.labels('getex', 'error').inc()
        }
    }

    async shutdown(): Promise<void> {
        // No local state to clean up in overflow lane implementation
    }
}
