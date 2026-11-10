import { ok } from '@posthog/ingestion-common/framework/results'
import { ProcessingStep } from '@posthog/ingestion-common/framework/steps'
import {
    EventIngestionRestrictionManager,
    RestrictionType,
} from '@posthog/node-common/utils/event-ingestion-restrictions/index'

import { EventHeaders, PipelineEvent, Team } from '~/types'

function applyPersonProcessingRestrictions(
    event: PipelineEvent,
    headers: EventHeaders,
    restrictions: ReadonlySet<RestrictionType>,
    team_person_processing_opt_out: boolean
): void {
    const hasSkipRestriction = restrictions.has(RestrictionType.SKIP_PERSON_PROCESSING)
    const shouldSkipPerson = hasSkipRestriction || team_person_processing_opt_out

    if (shouldSkipPerson) {
        if (event.properties) {
            event.properties.$process_person_profile = false
        } else {
            event.properties = { $process_person_profile: false }
        }
    }

    if (hasSkipRestriction) {
        headers.force_disable_person_processing = true
    }
}

export function createApplyPersonProcessingRestrictionsStep<
    T extends { event: PipelineEvent; team: Team; headers: EventHeaders },
>(eventIngestionRestrictionManager: EventIngestionRestrictionManager): ProcessingStep<T, T> {
    return async function applyPersonProcessingRestrictionsStep(input) {
        const { event, team, headers } = input

        const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions(headers.token, headers)
        applyPersonProcessingRestrictions(event, headers, restrictions, team.person_processing_opt_out ?? false)
        return Promise.resolve(ok(input))
    }
}
