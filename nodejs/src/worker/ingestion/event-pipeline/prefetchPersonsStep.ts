import { PipelineResult, ok } from '~/ingestion/pipelines/results'
import { EventHeaders, PipelineEvent, Team } from '~/types'

import { PersonsStore } from '../persons/persons-store'

type PrefetchPersonsStepInput = { event: PipelineEvent; team: Team; headers: EventHeaders }

export function prefetchPersonsStep<T extends PrefetchPersonsStepInput>(personsStore: PersonsStore, enabled: boolean) {
    return function prefetchPersonsStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled) {
            // Filter out events where person processing is disabled
            const eventsToPrefetch = events.filter((x) => !x.headers.force_disable_person_processing)

            if (eventsToPrefetch.length > 0) {
                // Fire prefetch without awaiting. fetchForChecking/fetchForUpdate will wait
                // on the pending promises if they need data that's still being fetched
                void personsStore.prefetchPersons(
                    eventsToPrefetch.map((x) => ({ teamId: x.team.id, distinctId: x.event.distinct_id }))
                )
            }
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}
