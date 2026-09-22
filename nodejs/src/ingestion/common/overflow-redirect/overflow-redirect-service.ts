import { EventHeaders, HealthCheckResult } from '~/types'

// Re-export OverflowType so consumers of the interface
// don't need to know about the repository layer
export type { OverflowType } from './overflow-redis-repository'

export interface OverflowEventGroup {
    /** The Kafka partition key capture computed, e.g. `token:distinct_id` or `token:client_ip`. */
    key: string
    /** Headers of each event for this key in the batch; strategies count their tokens from these. */
    headersPerEvent: EventHeaders[]
    firstTimestamp: number
}

/**
 * Service for handling stateful overflow redirects.
 * Implementations differ based on lane type (main vs overflow).
 */
export interface OverflowRedirectService {
    /**
     * Handle a batch of events grouped by partition key.
     *
     * - Main lane: Check if flagged, flag if rate limited, return set of keys to redirect
     * - Overflow lane: Refresh TTL for all keys, return empty set (no redirects)
     *
     * The overflow keyspace (`OverflowType`) is fixed per service instance and
     * supplied at construction — a given service belongs to exactly one pipeline.
     *
     * @returns Set of partition keys that should be redirected to overflow
     */
    handleEventBatch(batch: OverflowEventGroup[]): Promise<Set<string>>

    /**
     * Health check for the service
     */
    healthCheck(): Promise<HealthCheckResult>

    /**
     * Graceful shutdown
     */
    shutdown(): Promise<void>
}
