import { DateTime } from 'luxon'

import { Person, Team } from '../../types'
import { uuidFromDistinctId } from '../../worker/ingestion/person-uuid'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface DisablePersonProcessingWithFakePersonInput {
    team: Team
    event: { distinct_id: string }
}

/**
 * Pipeline step that disables person processing and provides a deterministic
 * fake person. Used in pipelines that skip person/group processing entirely
 * (e.g. the testing ingestion pipeline).
 *
 * The fake person UUID is deterministic based on team_id and distinct_id.
 */
export function createDisablePersonProcessingWithFakePersonStep<
    TInput extends DisablePersonProcessingWithFakePersonInput,
>(): ProcessingStep<TInput, TInput & { processPerson: boolean; person: Person }> {
    return function disablePersonProcessingWithFakePersonStep(
        input: TInput
    ): Promise<PipelineResult<TInput & { processPerson: boolean; person: Person }>> {
        const { team, event } = input
        const distinctId = String(event.distinct_id)

        // Deterministic fake person - same logic as createFakePerson in process-personless-step.ts
        const createdAt = DateTime.utc(1970, 1, 1, 0, 0, 5)
        const person: Person = {
            team_id: team.id,
            properties: {},
            uuid: uuidFromDistinctId(team.id, distinctId),
            created_at: createdAt,
        }

        return Promise.resolve(
            ok({
                ...input,
                processPerson: false,
                person,
            })
        )
    }
}
