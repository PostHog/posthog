import { PipelineResult, ok } from '~/ingestion/pipelines/results'
import { IncomingEventWithTeam } from '~/types'

import { PersonsStore } from '../persons/persons-store'

type prefetchPersonsStepInput = { eventWithTeam: IncomingEventWithTeam }
type prefetchPersonsStepOutput = { eventWithTeam: IncomingEventWithTeam }

export function prefetchPersonsStep<T extends prefetchPersonsStepInput>(personsStore: PersonsStore, enabled: boolean) {
    return async function prefetchPersonsStep(events: T[]): Promise<PipelineResult<T & prefetchPersonsStepOutput>[]> {
        if (enabled) {
            await personsStore.prefetchPersons(
                events.map((x) => ({ teamId: x.eventWithTeam.team.id, distinctId: x.eventWithTeam.event.distinct_id }))
            )
        }
        return events.map((event) => ok(event))
    }
}
