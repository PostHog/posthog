import { DateTime } from 'luxon'

import { PluginEvent } from '~/plugin-scaffold'

import { Person, Team } from '../../types'
import { uuidFromDistinctId } from '../../worker/ingestion/person-uuid'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export type ProcessPersonlessInput = {
    normalizedEvent: PluginEvent
    team: Team
    timestamp: DateTime
    processPerson: boolean
    forceDisablePersonProcessing: boolean
}

export type ProcessPersonlessOutput = {
    personlessPerson?: Person
}

/**
 * Pipeline step that handles personless event processing checks.
 *
 * When processPerson=false, this step:
 * 1. Fetches existing person from cache (populated by prefetchPersonsStep)
 * 2. Checks batch results for is_merged flag (populated by processPersonlessDistinctIdsBatchStep)
 * 3. Calculates force_upgrade flag
 * 4. Returns person (real or fake) with potential force_upgrade flag
 */
export function createProcessPersonlessStep<TInput extends ProcessPersonlessInput>(
    personsStore: PersonsStore
): ProcessingStep<TInput, TInput & ProcessPersonlessOutput> {
    return async function processPersonlessStep(
        input: TInput
    ): Promise<PipelineResult<TInput & ProcessPersonlessOutput>> {
        if (input.processPerson) {
            return ok(input)
        }

        const { normalizedEvent, team, timestamp, forceDisablePersonProcessing } = input
        const distinctId = normalizedEvent.distinct_id

        if (forceDisablePersonProcessing) {
            return ok({ ...input, personlessPerson: createFakePerson(team.id, distinctId) })
        }

        // Check if a real person exists for this distinct_id (from prefetch cache)
        let existingPerson = await personsStore.fetchForChecking(team.id, distinctId)

        if (!existingPerson) {
            // Check if batch insert found this distinct_id was merged
            // The batch step (processPersonlessDistinctIdsBatchStep) already did the INSERT
            // and stored is_merged=true results in the personsStore cache
            const personIsMerged = personsStore.getPersonlessBatchResult(team.id, distinctId)

            if (personIsMerged) {
                // If is_merged came back true, it means the posthog_personlessdistinctid
                // was updated by a merge. We need to fetch the person again (using the leader)
                // so that we properly associate this event with the Person we got merged into.
                existingPerson = await personsStore.fetchForUpdate(team.id, distinctId)
            }
        }

        if (existingPerson) {
            const person = existingPerson as Person

            // Ensure person properties don't propagate elsewhere, such as onto the event itself.
            person.properties = {}

            // If the team has opted out then we never force the upgrade.
            const teamHasNotOptedOut = !team.person_processing_opt_out
            if (teamHasNotOptedOut && timestamp > person.created_at.plus({ minutes: 1 })) {
                // See documentation on the Person.force_upgrade field.
                //
                // Note that we account for timestamp vs person creation time (with a little
                // padding for good measure) to account for ingestion lag. It's possible for
                // events to be processed after person creation even if they were sent prior
                // to person creation, and the user did nothing wrong in that case.
                person.force_upgrade = true
            }

            return ok({ ...input, personlessPerson: person })
        }

        return ok({ ...input, personlessPerson: createFakePerson(team.id, distinctId) })
    }
}

/**
 * Creates a deterministic fake person for personless events.
 *
 * The UUID is deterministic based on team_id and distinct_id, allowing:
 * - Future events with same distinct_id to get same UUID
 * - Later merging/upgrading without data loss
 *
 * The created_at timestamp (1970-01-01 00:00:05 UTC) serves as a debugging marker
 * that this is a synthetic person, not a real one.
 */
function createFakePerson(teamId: number, distinctId: string): Person {
    // We need a value from the `person_created_column` in ClickHouse. This should be
    // hidden from users for events without a real person, anyway. It's slightly offset
    // from the 0 date (by 5 seconds) in order to assist in debugging by being
    // harmlessly distinct from Unix UTC "0".
    const createdAt = DateTime.utc(1970, 1, 1, 0, 0, 5)

    return {
        team_id: teamId,
        properties: {},
        uuid: uuidFromDistinctId(teamId, distinctId),
        created_at: createdAt,
    }
}
