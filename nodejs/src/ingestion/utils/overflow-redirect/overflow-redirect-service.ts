import { HealthCheckResult } from '../../../types'
import { OverflowType } from './overflow-redis-repository'

// Re-export OverflowType so consumers of the interface
// don't need to know about the repository layer
export type { OverflowType } from './overflow-redis-repository'

export interface OverflowEventKey {
    token: string
    distinctId: string
}

export interface OverflowEventBatch {
    key: OverflowEventKey
    eventCount: number
    firstTimestamp: number
}

/**
 * Service for handling stateful overflow redirects.
 * Implementations differ based on lane type (main vs overflow).
 */
export interface OverflowRedirectService {
    /**
     * Handle a batch of events grouped by token:distinct_id.
     *
     * - Main lane: Check if flagged, flag if rate limited, return set of keys to redirect
     * - Overflow lane: Refresh TTL for all keys, return empty set (no redirects)
     *
     * @returns Set of keys (token:distinctId) that should be redirected to overflow
     */
    handleEventBatch(type: OverflowType, batch: OverflowEventBatch[]): Promise<Set<string>>

    /**
     * Health check for the service
     */
    healthCheck(): Promise<HealthCheckResult>

    /**
     * Graceful shutdown
     */
    shutdown(): Promise<void>
}
