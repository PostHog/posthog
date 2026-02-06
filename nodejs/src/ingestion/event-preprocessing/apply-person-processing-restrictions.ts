import { EventHeaders, IncomingEventWithTeam } from '../../types'
import { EventIngestionRestrictionManager, RestrictionType } from '../../utils/event-ingestion-restrictions'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

function applyPersonProcessingRestrictions(
    eventWithTeam: IncomingEventWithTeam,
    restrictions: ReadonlySet<RestrictionType>,
    team_person_processing_opt_out: boolean
): void {
    const { event } = eventWithTeam

    const shouldSkipPerson = restrictions.has(RestrictionType.SKIP_PERSON_PROCESSING) || team_person_processing_opt_out

    if (shouldSkipPerson) {
        if (event.properties) {
            event.properties.$process_person_profile = false
        } else {
            event.properties = { $process_person_profile: false }
        }
    }
}

export function createApplyPersonProcessingRestrictionsStep<
    T extends { eventWithTeam: IncomingEventWithTeam; headers: EventHeaders },
>(eventIngestionRestrictionManager: EventIngestionRestrictionManager): ProcessingStep<T, T> {
    return async function applyPersonProcessingRestrictionsStep(input) {
        const { eventWithTeam, headers } = input

        const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions(headers.token, headers)
        applyPersonProcessingRestrictions(
            eventWithTeam,
            restrictions,
            eventWithTeam.team.person_processing_opt_out ?? false
        )
        return Promise.resolve(ok(input))
    }
}
