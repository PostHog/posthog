import { LRUCache } from 'lru-cache'
import { Counter } from 'prom-client'

import { PipelineResult, ok } from '~/ingestion/pipelines/results'
import { IncomingEventWithTeam } from '~/types'

import { ONE_HOUR } from '../../../config/constants'
import { PersonsStore } from '../persons/persons-store'

type ProcessPersonlessDistinctIdsBatchStepInput = { eventWithTeam: IncomingEventWithTeam }

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
    personsStore: PersonsStore,
    enabled: boolean
) {
    return async function processPersonlessDistinctIdsBatchStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled) {
            // Deduplicate personless events within the batch first, then check cache
            const seenInBatch = new Set<string>()
            let cacheHits = 0
            const personlessEntries: { teamId: number; distinctId: string }[] = []

            for (const e of events) {
                if (e.eventWithTeam.event.properties?.$process_person_profile !== false) {
                    continue
                }
                const cacheKey = `${e.eventWithTeam.team.id}|${e.eventWithTeam.event.distinct_id}`

                // Skip if already seen in this batch
                if (seenInBatch.has(cacheKey)) {
                    continue
                }
                seenInBatch.add(cacheKey)

                if (PERSONLESS_DISTINCT_ID_INSERTED_CACHE.get(cacheKey)) {
                    cacheHits++
                } else {
                    personlessEntries.push({
                        teamId: e.eventWithTeam.team.id,
                        distinctId: e.eventWithTeam.event.distinct_id,
                    })
                }
            }

            if (cacheHits > 0) {
                personlessDistinctIdCacheOperationsCounter.inc({ operation: 'hit' }, cacheHits)
            }

            if (personlessEntries.length > 0) {
                personlessDistinctIdCacheOperationsCounter.inc({ operation: 'miss' }, personlessEntries.length)

                await personsStore.processPersonlessDistinctIdsBatch(personlessEntries)

                // Update LRU cache for all entries we just inserted
                for (const entry of personlessEntries) {
                    PERSONLESS_DISTINCT_ID_INSERTED_CACHE.set(`${entry.teamId}|${entry.distinctId}`, true)
                }
            }
        }
        return events.map((event) => ok(event))
    }
}
