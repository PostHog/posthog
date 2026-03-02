import { LRUCache } from 'lru-cache'
import { Counter } from 'prom-client'

import { PipelineResult, ok } from '~/ingestion/pipelines/results'
import { PipelineEvent, Team } from '~/types'

import { ONE_HOUR } from '../../../config/constants'
import { PersonsStore } from '../persons/persons-store'

type ProcessPersonlessDistinctIdsBatchStepInput = { event: PipelineEvent; team: Team; personsStore: PersonsStore }

export const personlessDistinctIdCacheOperationsCounter = new Counter({
    name: 'personless_distinct_id_cache_operations_total',
    help: 'Number of cache hits and misses for the personless distinct ID inserted cache',
    labelNames: ['operation'],
})

// Tracks whether we know we've already inserted a `posthog_personlessdistinctid` for the given
// (team_id, distinct_id) pair. If we have, then we can skip the INSERT attempt.
const PERSONLESS_DISTINCT_ID_INSERTED_CACHE = new LRUCache<string, boolean>({
    max: 100_000,
    ttl: ONE_HOUR * 4,
    updateAgeOnGet: true,
})

/**
 * Batch step that inserts personless distinct IDs for events where processPerson=false
 * and no person exists. This runs after prefetchPersonsStep so the person check cache
 * is already populated.
 *
 * The batch insert results (is_merged flags) are stored in the personsStore cache
 * and consumed by processPersonlessStep to determine force_upgrade.
 */
export function processPersonlessDistinctIdsBatchStep<T extends ProcessPersonlessDistinctIdsBatchStepInput>(
    enabled: boolean
) {
    return async function processPersonlessDistinctIdsBatchStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled && events.length > 0) {
            // Group personless entries by store instance — events in the same batch
            // may reference different stores
            const seenInBatch = new Set<string>()
            let cacheHits = 0
            const storeEntries = new Map<PersonsStore, { teamId: number; distinctId: string }[]>()

            for (const e of events) {
                if (e.event.properties?.$process_person_profile !== false) {
                    continue
                }
                const cacheKey = `${e.team.id}|${e.event.distinct_id}`

                if (seenInBatch.has(cacheKey)) {
                    continue
                }
                seenInBatch.add(cacheKey)

                if (PERSONLESS_DISTINCT_ID_INSERTED_CACHE.get(cacheKey)) {
                    cacheHits++
                } else {
                    let entries = storeEntries.get(e.personsStore)
                    if (!entries) {
                        entries = []
                        storeEntries.set(e.personsStore, entries)
                    }
                    entries.push({
                        teamId: e.team.id,
                        distinctId: e.event.distinct_id,
                    })
                }
            }

            if (cacheHits > 0) {
                personlessDistinctIdCacheOperationsCounter.inc({ operation: 'hit' }, cacheHits)
            }

            const promises: Promise<void>[] = []
            for (const [store, entries] of storeEntries) {
                personlessDistinctIdCacheOperationsCounter.inc({ operation: 'miss' }, entries.length)
                promises.push(store.processPersonlessDistinctIdsBatch(entries))
            }

            if (promises.length > 0) {
                await Promise.all(promises)

                // Update LRU cache for all entries we just inserted
                for (const entries of storeEntries.values()) {
                    for (const entry of entries) {
                        PERSONLESS_DISTINCT_ID_INSERTED_CACHE.set(`${entry.teamId}|${entry.distinctId}`, true)
                    }
                }
            }
        }
        return events.map((event) => ok(event))
    }
}
