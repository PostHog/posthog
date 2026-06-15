import { LRUCache } from 'lru-cache'
import { Counter } from 'prom-client'

import { PipelineResult, ok } from '~/ingestion/pipelines/results'
import { PipelineEvent, Team } from '~/types'

import { ONE_HOUR } from '../../../config/constants'
import { PersonsStoreForBatch } from '../persons/persons-store-for-batch'

type ProcessPersonlessDistinctIdsBatchStepInput = {
    event: PipelineEvent
    team: Team
    personsStoreForBatch: PersonsStoreForBatch
}

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
        if (enabled) {
            // Events in a chunk may come from different Kafka batches (due to the feed primitive).
            // Group by personsStoreForBatch so each batch's is_merged results land in the right
            // cache. Deduplicate per batch to avoid redundant DB calls within the same batch.
            type StoreData = { seenInBatch: Set<string>; entries: { teamId: number; distinctId: string }[] }
            const entriesByStore = new Map<PersonsStoreForBatch, StoreData>()
            let cacheHits = 0

            for (const e of events) {
                if (e.event.properties?.$process_person_profile !== false) {
                    continue
                }
                const cacheKey = `${e.team.id}|${e.event.distinct_id}`

                let storeData = entriesByStore.get(e.personsStoreForBatch)
                if (!storeData) {
                    storeData = { seenInBatch: new Set(), entries: [] }
                    entriesByStore.set(e.personsStoreForBatch, storeData)
                }

                if (storeData.seenInBatch.has(cacheKey)) {
                    continue
                }
                storeData.seenInBatch.add(cacheKey)

                if (PERSONLESS_DISTINCT_ID_INSERTED_CACHE.get(cacheKey)) {
                    cacheHits++
                } else {
                    storeData.entries.push({ teamId: e.team.id, distinctId: e.event.distinct_id })
                }
            }

            if (cacheHits > 0) {
                personlessDistinctIdCacheOperationsCounter.inc({ operation: 'hit' }, cacheHits)
            }

            const storeCalls = Array.from(entriesByStore.entries()).filter(([, { entries }]) => entries.length > 0)

            if (storeCalls.length > 0) {
                const totalMisses = storeCalls.reduce((sum, [, { entries }]) => sum + entries.length, 0)
                personlessDistinctIdCacheOperationsCounter.inc({ operation: 'miss' }, totalMisses)

                await Promise.all(
                    storeCalls.map(async ([store, { entries }]) => {
                        await store.processPersonlessDistinctIdsBatch(entries)
                        for (const entry of entries) {
                            PERSONLESS_DISTINCT_ID_INSERTED_CACHE.set(`${entry.teamId}|${entry.distinctId}`, true)
                        }
                    })
                )
            }
        }
        return events.map((event) => ok(event))
    }
}
