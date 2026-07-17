import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { PipelineEvent, Team } from '~/types'

type PrefetchPersonsStepInput = { event: PipelineEvent; team: Team; personsStoreForBatch: PersonsStoreForBatch }

export function prefetchPersonsStep<T extends PrefetchPersonsStepInput>(enabled: boolean) {
    return function prefetchPersonsStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled && events.length > 0) {
            // Events in a chunk may come from different Kafka batches (due to the feed primitive).
            // Group by batch store so each store only receives entries it owns. Fire without
            // awaiting — fetchForChecking/fetchForUpdate will wait on the pending promises if
            // they need data that's still being fetched.
            const entriesByStore = new Map<
                PersonsStoreForBatch,
                { teamId: number; distinctId: string; batchId: number }[]
            >()

            for (const event of events) {
                let entries = entriesByStore.get(event.personsStoreForBatch)
                if (!entries) {
                    entries = []
                    entriesByStore.set(event.personsStoreForBatch, entries)
                }
                entries.push({
                    teamId: event.team.id,
                    distinctId: event.event.distinct_id,
                    batchId: event.personsStoreForBatch.batchId,
                })
            }

            for (const [store, entries] of entriesByStore) {
                void store.prefetchPersons(entries)
            }
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}
