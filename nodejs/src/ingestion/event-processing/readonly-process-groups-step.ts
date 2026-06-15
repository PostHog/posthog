import { PreIngestionEvent, Team } from '../../types'
import { ReadOnlyGroupTypeManager } from '../../worker/ingestion/readonly-group-type-manager'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'
import { enrichPropertiesWithGroupTypes } from './groups'

export interface ReadOnlyProcessGroupsStepInput {
    preparedEvent: PreIngestionEvent
    team: Team
    processPerson: boolean
}

export type ReadOnlyProcessGroupsStepResult<TInput> = TInput

export function createReadOnlyProcessGroupsStep<TInput extends ReadOnlyProcessGroupsStepInput>(
    groupTypeManager: ReadOnlyGroupTypeManager
): ProcessingStep<TInput, ReadOnlyProcessGroupsStepResult<TInput>> {
    return async function readOnlyProcessGroupsStep(input: TInput) {
        const { preparedEvent, team, processPerson } = input

        if (processPerson && preparedEvent.properties.$groups) {
            const groupTypes = await groupTypeManager.fetchGroupTypes(team.project_id)
            enrichPropertiesWithGroupTypes(preparedEvent.properties, groupTypes)
        }

        return ok(input)
    }
}
