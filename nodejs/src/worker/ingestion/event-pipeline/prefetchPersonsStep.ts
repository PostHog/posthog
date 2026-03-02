import { PipelineResult, ok } from '~/ingestion/pipelines/results'
import { PipelineEvent, Team } from '~/types'

import { PersonsStore } from '../persons/persons-store'

type PrefetchPersonsStepInput = { event: PipelineEvent; team: Team; personsStore: PersonsStore }

export function prefetchPersonsStep<T extends PrefetchPersonsStepInput>(enabled: boolean) {
    return function prefetchPersonsStep(events: T[]): Promise<PipelineResult<T>[]> {
        if (enabled && events.length > 0) {
            // Group by store instance — events in the same batch may reference different stores
            const storeParams = new Map<PersonsStore, { teamId: number; distinctId: string }[]>()
            for (const e of events) {
                let params = storeParams.get(e.personsStore)
                if (!params) {
                    params = []
                    storeParams.set(e.personsStore, params)
                }
                params.push({ teamId: e.team.id, distinctId: e.event.distinct_id })
            }
            // Fire prefetch without awaiting. fetchForChecking/fetchForUpdate will wait
            // on the pending promises if they need data that's still being fetched
            for (const [store, params] of storeParams) {
                void store.prefetchPersons(params)
            }
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }
}
