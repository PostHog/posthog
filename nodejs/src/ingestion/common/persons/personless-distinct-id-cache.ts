import { LRUCache } from 'lru-cache'
import { Counter } from 'prom-client'

import { ONE_HOUR } from '~/common/config/constants'

export const personlessDistinctIdCacheOperationsCounter = new Counter({
    name: 'personless_distinct_id_cache_operations_total',
    help: 'Number of cache hits and misses for the personless distinct ID inserted cache',
    // `source` separates the batched personless step from the per-event $feature_flag_called
    // path so a high-volume flag-called miss rate can be read on its own during rollout.
    labelNames: ['operation', 'source'],
})

// Tracks whether we know we've already inserted a `posthog_personlessdistinctid` for the given
// (team_id, distinct_id) pair. If we have, then we can skip the INSERT attempt.
const PERSONLESS_DISTINCT_ID_INSERTED_CACHE = new LRUCache<string, boolean>({
    max: 100_000,
    ttl: ONE_HOUR * 4,
    updateAgeOnGet: true,
})

export function hasInsertedPersonlessDistinctId(teamId: number, distinctId: string): boolean {
    return PERSONLESS_DISTINCT_ID_INSERTED_CACHE.get(`${teamId}|${distinctId}`) === true
}

export function markPersonlessDistinctIdInserted(teamId: number, distinctId: string): void {
    PERSONLESS_DISTINCT_ID_INSERTED_CACHE.set(`${teamId}|${distinctId}`, true)
}
