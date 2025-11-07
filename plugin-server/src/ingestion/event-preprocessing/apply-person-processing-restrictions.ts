import { PipelineEvent, Team } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

function applyPersonProcessingRestrictions(
    event: PipelineEvent,
    team: Team,
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): void {
    const shouldSkipPersonRestriction = eventIngestionRestrictionManager.shouldSkipPerson(
        event.token,
        event.distinct_id
    )
    const shouldSkipPersonOptOut = team.person_processing_opt_out
    const shouldSkipPerson = shouldSkipPersonRestriction || shouldSkipPersonOptOut

    if (shouldSkipPerson) {
        if (event.properties) {
            event.properties.$process_person_profile = false
        } else {
            event.properties = { $process_person_profile: false }
        }
    }
}

export function createApplyPersonProcessingRestrictionsStep<T extends { event: PipelineEvent; team: Team }>(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): ProcessingStep<T, T> {
    return async function applyPersonProcessingRestrictionsStep(input) {
        const { event, team } = input
        applyPersonProcessingRestrictions(event, team, eventIngestionRestrictionManager)
        return Promise.resolve(ok(input))
    }
}
