import { Message } from 'node-rdkafka'

import { EventHeaders, IncomingEventWithTeam } from '../../types'
import { EventIngestionRestrictionManager } from '../../utils/event-ingestion-restriction-manager'
import { success } from '../../worker/ingestion/event-pipeline/pipeline-step-result'
import { SyncPreprocessingStep } from '../preprocessing-pipeline'

export function applyPersonProcessingRestrictions(
    eventWithTeam: IncomingEventWithTeam,
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): void {
    const { event, team } = eventWithTeam

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

export function createApplyPersonProcessingRestrictionsStep(
    eventIngestionRestrictionManager: EventIngestionRestrictionManager
): SyncPreprocessingStep<
    { message: Message; headers: EventHeaders; eventWithTeam: IncomingEventWithTeam },
    IncomingEventWithTeam
> {
    return (input) => {
        const { eventWithTeam } = input

        applyPersonProcessingRestrictions(eventWithTeam, eventIngestionRestrictionManager)

        return success(eventWithTeam)
    }
}
