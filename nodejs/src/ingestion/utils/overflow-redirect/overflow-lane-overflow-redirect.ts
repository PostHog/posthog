import { HealthCheckResult } from '../../../types'
import { overflowRedirectEventsTotal, overflowRedirectKeysTotal } from './metrics'
import { OverflowEventBatch, OverflowRedirectService } from './overflow-redirect-service'
import { OverflowRedisRepository, OverflowType } from './overflow-redis-repository'

export interface OverflowLaneOverflowRedirectConfig {
    redisRepository: OverflowRedisRepository
}

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
export class OverflowLaneOverflowRedirect implements OverflowRedirectService {
    private redisRepository: OverflowRedisRepository

    constructor(config: OverflowLaneOverflowRedirectConfig) {
        this.redisRepository = config.redisRepository
    }

    async handleEventBatch(type: OverflowType, batch: OverflowEventBatch[]): Promise<Set<string>> {
        // Refresh TTL for all keys in the batch
        if (batch.length > 0) {
            await this.redisRepository.batchRefreshTTL(
                type,
                batch.map((e) => e.key)
            )
        }

        // Record key-level metrics - all keys pass through (no redirects in overflow lane)
        overflowRedirectKeysTotal.labels(type, 'passed').inc(batch.length)

        // Record event-level metrics - sum up all event counts
        const totalEvents = batch.reduce((sum, event) => sum + event.eventCount, 0)
        overflowRedirectEventsTotal.labels(type, 'passed').inc(totalEvents)

        // Never redirect from overflow lane - return empty set
        return new Set()
    }

    async healthCheck(): Promise<HealthCheckResult> {
        return this.redisRepository.healthCheck()
    }

    async shutdown(): Promise<void> {
        // No local state to clean up in overflow lane implementation
    }
}
