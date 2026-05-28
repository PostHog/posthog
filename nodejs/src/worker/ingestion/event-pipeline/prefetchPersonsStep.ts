import { PipelineResult, ok } from '~/ingestion/pipelines/results'
import { PipelineEvent, Team } from '~/types'

import { PersonsStoreForBatch } from '../persons/persons-store-for-batch'

type PrefetchPersonsStepInput = { event: PipelineEvent; team: Team; personsStoreForBatch: PersonsStoreForBatch }

export function prefetchPersonsStep<T extends PrefetchPersonsStepInput>(enabled: boolean) {
    return function prefetchPersonsStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled && events.length > 0) {
            // Fire prefetch without awaiting. fetchForChecking/fetchForUpdate will wait
            // on the pending promises if they need data that's still being fetched
            void events[0].personsStoreForBatch.prefetchPersons(
                events.map((x) => ({ teamId: x.team.id, distinctId: x.event.distinct_id }))
            )
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}
