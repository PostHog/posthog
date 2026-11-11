import { ok } from '@posthog/ingestion-common/framework/results'
import { ProcessingStep } from '@posthog/ingestion-common/framework/steps'
import { ReadOnlyGroupTypeManager } from '@posthog/ingestion-common/groups/readonly-group-type-manager'

import { PreIngestionEvent, Team } from '~/types'

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
