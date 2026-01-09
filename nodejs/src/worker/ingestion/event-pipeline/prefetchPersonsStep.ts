import { PipelineResult, ok } from '~/ingestion/pipelines/results'
import { IncomingEventWithTeam } from '~/types'

import { PersonsStore } from '../persons/persons-store'

type PrefetchPersonsStepInput = { eventWithTeam: IncomingEventWithTeam }

export function prefetchPersonsStep<T extends PrefetchPersonsStepInput>(personsStore: PersonsStore, enabled: boolean) {
    return function prefetchPersonsStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled) {
            // Fire prefetch without awaiting. fetchForChecking/fetchForUpdate will wait
            // on the pending promises if they need data that's still being fetched
            void personsStore.prefetchPersons(
                events.map((x) => ({ teamId: x.eventWithTeam.team.id, distinctId: x.eventWithTeam.event.distinct_id }))
            )
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}
