import LRU from 'lru-cache'
import { DateTime } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { ONE_HOUR } from '../../../config/constants'
import { PipelineResult, ok } from '../../../ingestion/pipelines/results'
import { Person, Team } from '../../../types'
import { uuidFromDistinctId } from '../person-uuid'
import { PersonsStoreForBatch } from '../persons/persons-store-for-batch'

// Tracks whether we know we've already inserted a `posthog_personlessdistinctid` for the given
// (team_id, distinct_id) pair. If we have, then we can skip the INSERT attempt.
const PERSONLESS_DISTINCT_ID_INSERTED_CACHE = new LRU<string, boolean>({
    max: 10_000,
    maxAge: ONE_HOUR * 24, // cache up to 24h
    updateAgeOnGet: true,
})

/**
 * Pipeline step that handles personless event processing checks.
 *
 * This step runs when processPerson=false, and performs:
 * 1. Database fetch for existing person
 * 2. Insert into posthog_personlessdistinctid tracking table
 * 3. Merge detection via race condition handling
 * 4. force_upgrade flag calculation
 * 5. Returns person (real or fake) with potential force_upgrade flag
 *
 * The caller should check person.force_upgrade to decide if full person processing is needed.
 */
export async function processPersonlessStep(
    event: PluginEvent,
    team: Team,
    timestamp: DateTime,
    personStoreBatch: PersonsStoreForBatch,
    forceDisablePersonProcessing: boolean = false
): Promise<PipelineResult<Person>> {
    const distinctId = String(event.distinct_id)

    // If forceDisablePersonProcessing is true, skip all personless processing and just create a fake person
    if (forceDisablePersonProcessing) {
        return ok(createFakePerson(team.id, distinctId))
    }

    // Check if a real person exists for this distinct_id
    let existingPerson = await personStoreBatch.fetchForChecking(team.id, distinctId)

    if (!existingPerson) {
        // See the comment in `mergeDistinctIds`. We are inserting a row into `posthog_personlessdistinctid`
        // to note that this Distinct ID has been used in "personless" mode. This is necessary
        // so that later, during a merge, we can decide whether we need to write out an override
        // or not.

        const personlessDistinctIdCacheKey = `${team.id}|${distinctId}`
        if (!PERSONLESS_DISTINCT_ID_INSERTED_CACHE.get(personlessDistinctIdCacheKey)) {
            const personIsMerged = await personStoreBatch.addPersonlessDistinctId(team.id, distinctId)

            // We know the row is in PG now, and so future events for this Distinct ID can
            // skip the PG I/O.
            PERSONLESS_DISTINCT_ID_INSERTED_CACHE.set(personlessDistinctIdCacheKey, true)

            if (personIsMerged) {
                // If `personIsMerged` comes back `true`, it means the `posthog_personlessdistinctid`
                // has been updated by a merge (either since we called `fetchPerson` above, plus
                // replication lag). We need to check `fetchPerson` again (this time using the leader)
                // so that we properly associate this event with the Person we got merged into.
                existingPerson = await personStoreBatch.fetchForUpdate(team.id, distinctId)
            }
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

        return ok(person)
    }

    // No existing person found - create a fake person
    return ok(createFakePerson(team.id, distinctId))
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
