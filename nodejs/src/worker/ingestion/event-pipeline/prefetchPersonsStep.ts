import { PipelineResult, ok } from '~/ingestion/pipelines/results'
import { PipelineEvent, Team } from '~/types'

import { PersonsStoreForBatch } from '../persons/persons-store-for-batch'

type PrefetchPersonsStepInput = { event: PipelineEvent; team: Team; personsStoreForBatch: PersonsStoreForBatch }

export function prefetchPersonsStep<T extends PrefetchPersonsStepInput>(enabled: boolean) {
    return function prefetchPersonsStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled && events.length > 0) {
            // Events in a chunk may come from different Kafka batches (due to the feed primitive).
            // The underlying persons store is shared across batches, so we issue a single DB fetch
            // and tag each entry with its event's batchId so cache eviction tracking lands on the
            // correct batch. Fire without awaiting — fetchForChecking/fetchForUpdate will wait
            // on the pending promises if they need data that's still being fetched.
            void events[0].personsStoreForBatch.prefetchPersons(
                events.map((x) => ({
                    teamId: x.team.id,
                    distinctId: x.event.distinct_id,
                    batchId: x.personsStoreForBatch.batchId,
                }))
            )
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}
