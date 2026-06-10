import { PipelineResult, ok } from '~/ingestion/pipelines/results'
import { PipelineEvent, Team } from '~/types'

import {
    hasInsertedPersonlessDistinctId,
    markPersonlessDistinctIdInserted,
    personlessDistinctIdCacheOperationsCounter,
} from '../persons/personless-distinct-id-cache'
import { PersonsStore } from '../persons/persons-store'

type ProcessPersonlessDistinctIdsBatchStepInput = { event: PipelineEvent; team: Team }

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
                if (e.event.properties?.$process_person_profile !== false) {
                    continue
                }
                const cacheKey = `${e.team.id}|${e.event.distinct_id}`

                // Skip if already seen in this batch
                if (seenInBatch.has(cacheKey)) {
                    continue
                }
                seenInBatch.add(cacheKey)

                if (hasInsertedPersonlessDistinctId(e.team.id, e.event.distinct_id)) {
                    cacheHits++
                } else {
                    personlessEntries.push({
                        teamId: e.team.id,
                        distinctId: e.event.distinct_id,
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
                    markPersonlessDistinctIdInserted(entry.teamId, entry.distinctId)
                }
            }
        }
        return events.map((event) => ok(event))
    }
}
