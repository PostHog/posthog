import { PluginEvent } from '@posthog/plugin-scaffold'

import { EventHeaders, Team } from '../../types'
import { EventIngestionRestrictionManager, RestrictionType } from '../../utils/event-ingestion-restrictions'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

function applyPersonProcessingRestrictions(
    event: PluginEvent,
    restrictions: ReadonlySet<RestrictionType>,
    team_person_processing_opt_out: boolean
): void {
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
    T extends { event: PluginEvent; team: Team; headers: EventHeaders },
>(eventIngestionRestrictionManager: EventIngestionRestrictionManager): ProcessingStep<T, T> {
    return async function applyPersonProcessingRestrictionsStep(input) {
        const { event, team, headers } = input

        const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions(headers.token, headers)
        applyPersonProcessingRestrictions(event, restrictions, team.person_processing_opt_out ?? false)
        return Promise.resolve(ok(input))
    }
}
