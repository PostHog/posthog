import {
    buildFlagCalledPersonlessMatcher,
    isFlagCalledPersonlessCandidate,
} from '~/ingestion/common/persons/flag-called-personless'
import {
    hasInsertedPersonlessDistinctId,
    markPersonlessDistinctIdInserted,
    personlessDistinctIdCacheOperationsCounter,
} from '~/ingestion/common/persons/personless-distinct-id-cache'
import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { DEFAULT_FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS } from '~/ingestion/config'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { PipelineEvent, Team } from '~/types'

type ProcessPersonlessDistinctIdsChunkStepInput = {
    event: PipelineEvent
    team: Team
    personsStoreForBatch: PersonsStoreForBatch
}

type PersonlessSource = 'batch' | 'flag_called'

/**
 * Chunk step that inserts personless distinct IDs into posthog_personlessdistinctid. This
 * runs after prefetchPersonsStep (which fires off person-existence fetches in the background)
 * and before the per-event processPersonlessStep, which awaits those fetches via fetchForChecking
 * and reads the is_merged results stored here.
 *
 * Two kinds of events are inserted, both via the same UNNEST batch insert:
 *  - "batch": events explicitly marked personless ($process_person_profile === false).
 *  - "flag_called": $feature_flag_called events that default to personless for enabled teams
 *    (see #60581). Batching these here avoids one single-row insert per first-seen distinct
 *    ID in processPersonlessStep, which contends on the table's incrementing-integer PK at
 *    high volume. The per-event step still makes the final personless/personful decision; it
 *    just finds the row already inserted (LRU hit) and skips its own insert. The single-row
 *    insert remains the fallback when this step is disabled.
 *
 * Inserting a row for a flag_called distinct ID that turns out to have a real person is
 * harmless: the explicit-personless path already inserts unconditionally, every reader is
 * gated on the absence of a real person, and coexistence is the normal post-merge state. So
 * this step does not need a per-row person check.
 */
export function processPersonlessDistinctIdsChunkStep<T extends ProcessPersonlessDistinctIdsChunkStepInput>(
    enabled: boolean,
    flagCalledPersonlessDefaultTeams: string = DEFAULT_FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS
) {
    const flagCalledDefaultEnabledForTeam = buildFlagCalledPersonlessMatcher(flagCalledPersonlessDefaultTeams)

    return async function processPersonlessDistinctIdsChunkStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled) {
            // Events in a chunk may come from different Kafka batches (due to the feed primitive).
            // Group by personsStoreForBatch so each batch's is_merged results land in the right
            // cache. Deduplicate per batch to avoid redundant DB calls within the same batch.
            type StoreData = { seenInBatch: Set<string>; entries: { teamId: number; distinctId: string }[] }
            const entriesByStore = new Map<PersonsStoreForBatch, StoreData>()
            const cacheHits: Record<PersonlessSource, number> = { batch: 0, flag_called: 0 }
            const cacheMisses: Record<PersonlessSource, number> = { batch: 0, flag_called: 0 }

            for (const e of events) {
                const source = personlessSource(e, flagCalledDefaultEnabledForTeam)
                if (source === null) {
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

                if (hasInsertedPersonlessDistinctId(e.team.id, e.event.distinct_id)) {
                    cacheHits[source]++
                } else {
                    cacheMisses[source]++
                    storeData.entries.push({ teamId: e.team.id, distinctId: e.event.distinct_id })
                }
            }

            for (const source of ['batch', 'flag_called'] as const) {
                if (cacheHits[source] > 0) {
                    personlessDistinctIdCacheOperationsCounter.inc({ operation: 'hit', source }, cacheHits[source])
                }
                if (cacheMisses[source] > 0) {
                    personlessDistinctIdCacheOperationsCounter.inc({ operation: 'miss', source }, cacheMisses[source])
                }
            }

            const storeCalls = Array.from(entriesByStore.entries()).filter(([, { entries }]) => entries.length > 0)

            if (storeCalls.length > 0) {
                await Promise.all(
                    storeCalls.map(async ([store, { entries }]) => {
                        await store.processPersonlessDistinctIdsBatch(entries)
                        for (const entry of entries) {
                            markPersonlessDistinctIdInserted(entry.teamId, entry.distinctId)
                        }
                    })
                )
            }
        }
        return events.map((event) => ok(event))
    }
}

function personlessSource(
    e: ProcessPersonlessDistinctIdsChunkStepInput,
    flagCalledDefaultEnabledForTeam: (teamId: number) => boolean
): PersonlessSource | null {
    const processPersonProfile = e.event.properties?.$process_person_profile
    if (processPersonProfile === false) {
        return 'batch'
    }
    // The per-event step uses the captured processPersonExplicitlyTrue; this step runs before
    // normalizeProcessPerson strips the property, so reading it from the raw event is valid.
    const processPersonExplicitlyTrue = processPersonProfile === true
    if (
        isFlagCalledPersonlessCandidate(
            e.event,
            e.team.id,
            processPersonExplicitlyTrue,
            flagCalledDefaultEnabledForTeam
        )
    ) {
        return 'flag_called'
    }
    return null
}
