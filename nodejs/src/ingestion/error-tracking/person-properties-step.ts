import { PluginEvent } from '~/plugin-scaffold'
import { Person, Team } from '~/types'
import { PersonRepository } from '~/worker/ingestion/persons/repositories/person-repository'

import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface PersonPropertiesInput {
    event: PluginEvent
    team: Team
}

/**
 * Creates a step that fetches person data for error tracking events.
 *
 * This is a read-only step that fetches person data from the database
 * and passes it downstream. It does not create or update persons, and
 * does not modify event properties.
 *
 * The person object is used by downstream steps (createCreateEventStep)
 * to set the top-level person_id, person_properties, and person_created_at
 * fields on the ClickHouse event.
 */
export function createPersonPropertiesReadOnlyStep<T extends PersonPropertiesInput>(
    personRepository: PersonRepository
): ProcessingStep<T, T & { person: Person | null }> {
    return async function personPropertiesReadOnlyStep(input) {
        const { event, team } = input

        // If no distinct_id, pass through without lookup
        if (!event.distinct_id) {
            return ok({ ...input, person: null })
        }

        // Fetch person from database (read-only, no updates)
        const person = await personRepository.fetchPerson(team.id, event.distinct_id, {
            useReadReplica: true,
        })

        // Pass through with person (or null if not found)
        return ok({ ...input, person: person ?? null })
    }
}
