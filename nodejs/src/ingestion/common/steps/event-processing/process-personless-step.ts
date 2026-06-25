import { DateTime } from 'luxon'

import { normalizeProcessPerson } from '~/common/utils/event'
import {
    buildFlagCalledPersonlessMatcher,
    isFlagCalledPersonlessCandidate,
} from '~/ingestion/common/flag-called-personless'
import { uuidFromDistinctId } from '~/ingestion/common/person-uuid'
import {
    hasInsertedPersonlessDistinctId,
    markPersonlessDistinctIdInserted,
    personlessDistinctIdCacheOperationsCounter,
} from '~/ingestion/common/persons/personless-distinct-id-cache'
import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { DEFAULT_FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS } from '~/ingestion/config'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { PluginEvent } from '~/plugin-scaffold'
import { Person, Team } from '~/types'

export type ProcessPersonlessInput = {
    normalizedEvent: PluginEvent
    team: Team
    timestamp: DateTime
    processPerson: boolean
    processPersonExplicitlyTrue: boolean
    forceDisablePersonProcessing: boolean
    personsStoreForBatch: PersonsStoreForBatch
}

export type ProcessPersonlessOutput = {
    personlessPerson?: Person
}

/**
 * Pipeline step that handles personless event processing checks.
 *
 * Runs when processPerson=false, and also for $feature_flag_called events that did not
 * explicitly set $process_person_profile=true — so server-side flag evaluation does not
 * create orphan person profiles (see #60581). Flag-called events that find an existing
 * person, or that carry group keys, stay personful; the rest are defaulted to personless.
 *
 * For personless events, this step:
 * 1. Fetches existing person from cache (populated by prefetchPersonsStep)
 * 2. Checks batch results for is_merged flag (populated by processPersonlessDistinctIdsBatchStep)
 * 3. Calculates force_upgrade flag
 * 4. Returns person (real or fake) with potential force_upgrade flag
 */
export function createProcessPersonlessStep<TInput extends ProcessPersonlessInput>(
    flagCalledPersonlessDefaultTeams: string = DEFAULT_FLAG_CALLED_PERSONLESS_DEFAULT_TEAMS
): ProcessingStep<TInput, TInput & ProcessPersonlessOutput> {
    const flagCalledDefaultEnabledForTeam = buildFlagCalledPersonlessMatcher(flagCalledPersonlessDefaultTeams)

    return async function processPersonlessStep(
        input: TInput
    ): Promise<PipelineResult<TInput & ProcessPersonlessOutput>> {
        if (input.processPerson) {
            const mayDefaultFlagCalledToPersonless = isFlagCalledPersonlessCandidate(
                input.normalizedEvent,
                input.team.id,
                input.processPersonExplicitlyTrue,
                flagCalledDefaultEnabledForTeam
            )

            if (!mayDefaultFlagCalledToPersonless) {
                return ok(input)
            }

            return await applyFeatureFlagCalledPersonlessDefault(input, input.personsStoreForBatch)
        }

        const { normalizedEvent, team, timestamp, forceDisablePersonProcessing, personsStoreForBatch } = input
        const distinctId = normalizedEvent.distinct_id

        if (forceDisablePersonProcessing) {
            return ok({ ...input, personlessPerson: createFakePerson(team.id, distinctId) })
        }

        // Check if a real person exists for this distinct_id (from prefetch cache)
        let existingPerson = await personsStoreForBatch.fetchForChecking(team.id, distinctId)

        if (!existingPerson) {
            // Check if batch insert found this distinct_id was merged
            // The batch step (processPersonlessDistinctIdsBatchStep) already did the INSERT
            // and stored is_merged=true results in the personsStore cache
            const personIsMerged = personsStoreForBatch.getPersonlessBatchResult(team.id, distinctId)

            if (personIsMerged) {
                // If is_merged came back true, it means the posthog_personlessdistinctid
                // was updated by a merge. We need to fetch the person again (using the leader)
                // so that we properly associate this event with the Person we got merged into.
                existingPerson = await personsStoreForBatch.fetchForUpdate(team.id, distinctId)
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
 * Defaults a $feature_flag_called event to personless unless a person already exists for
 * its distinct ID, so server-side flag evaluation does not create orphan person profiles.
 */
async function applyFeatureFlagCalledPersonlessDefault<TInput extends ProcessPersonlessInput>(
    input: TInput,
    personsStore: PersonsStoreForBatch
): Promise<PipelineResult<TInput & ProcessPersonlessOutput>> {
    const { normalizedEvent, team } = input
    const distinctId = normalizedEvent.distinct_id

    let existingPerson = await personsStore.fetchForChecking(team.id, distinctId)

    if (!existingPerson) {
        let personIsMerged = personsStore.getPersonlessBatchResult(team.id, distinctId)

        if (personIsMerged === undefined) {
            if (hasInsertedPersonlessDistinctId(team.id, distinctId)) {
                // The LRU keeps repeat distinct IDs from re-inserting on every event; a stale
                // hit just means the event goes personless, the same trade-off the batch step
                // accepts.
                personlessDistinctIdCacheOperationsCounter.inc({ operation: 'hit', source: 'flag_called' })
            } else {
                personlessDistinctIdCacheOperationsCounter.inc({ operation: 'miss', source: 'flag_called' })
                // The batch step (processPersonlessDistinctIdsBatchStep) pre-inserts flag_called
                // rows when enabled, but it may be disabled or this distinct ID may be first-seen,
                // so record it here when the LRU shows no prior insert. Without the row, a later
                // identify/merge would never re-point these events at the merged person.
                personIsMerged = await personsStore.addPersonlessDistinctId(team.id, distinctId)
                markPersonlessDistinctIdInserted(team.id, distinctId)
            }
        }

        if (personIsMerged) {
            // The posthog_personlessdistinctid row was updated by a merge, so fetch the
            // person again (using the leader) to associate this event with the merge target.
            existingPerson = await personsStore.fetchForUpdate(team.id, distinctId)
        }
    }

    if (existingPerson) {
        // A person already exists for this distinct ID, so keep the event personful.
        return ok(input)
    }

    return ok({
        ...input,
        // The event was normalized as personful upstream, so re-normalize it to strip
        // $set/$set_once and stamp $process_person_profile=false.
        normalizedEvent: normalizeProcessPerson(normalizedEvent, false),
        processPerson: false,
        personlessPerson: createFakePerson(team.id, distinctId),
    })
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
