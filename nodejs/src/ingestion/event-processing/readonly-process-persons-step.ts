import { DateTime } from 'luxon'

import { PluginEvent } from '~/plugin-scaffold'

import { Person, Team } from '../../types'
import {
    PropertyUpdates,
    applyEventPropertyUpdates,
    computeEventPropertyUpdates,
} from '../../worker/ingestion/persons/person-update'
import { PersonsStore } from '../../worker/ingestion/persons/persons-store'
import { PipelineResult, ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export type ReadonlyProcessPersonsInput = {
    normalizedEvent: PluginEvent
    team: Team
    timestamp: DateTime
    personlessPerson?: Person
}

export type ReadonlyProcessPersonsOutput = {
    person?: Person
    personPropertyUpdates?: PropertyUpdates
}

/**
 * Read-only variant of the process persons step for the testing pipeline.
 *
 * If a personlessPerson is already set (without force_upgrade), it is used
 * directly — mirroring the short-circuit in the original processPersonsStep.
 *
 * Otherwise, fetches the person from the store (read replica), computes
 * property updates from the event's $set/$set_once/$unset, and applies them
 * to produce a merged person — without writing to Postgres.
 *
 * If no person exists for the distinct ID, returns no person.
 */
export function createReadonlyProcessPersonsStep<TInput extends ReadonlyProcessPersonsInput>(
    personsStore: PersonsStore
): ProcessingStep<TInput, TInput & ReadonlyProcessPersonsOutput> {
    return async function readonlyProcessPersonsStep(
        input: TInput
    ): Promise<PipelineResult<TInput & ReadonlyProcessPersonsOutput>> {
        const { normalizedEvent, team, personlessPerson } = input

        if (personlessPerson && !personlessPerson.force_upgrade) {
            return ok({ ...input, person: personlessPerson, personPropertyUpdates: undefined })
        }

        const existingPerson = await personsStore.fetchForChecking(team.id, normalizedEvent.distinct_id)

        if (existingPerson) {
            existingPerson.properties ||= {}

            const personPropertyUpdates = computeEventPropertyUpdates(normalizedEvent, existingPerson.properties)
            const [mergedPerson] = applyEventPropertyUpdates(personPropertyUpdates, existingPerson)

            const person: Person = {
                team_id: mergedPerson.team_id,
                properties: mergedPerson.properties,
                uuid: mergedPerson.uuid,
                created_at: mergedPerson.created_at,
            }

            if (personlessPerson?.force_upgrade) {
                person.force_upgrade = true
            }

            return ok({ ...input, person, personPropertyUpdates })
        }

        return ok({ ...input, person: undefined, personPropertyUpdates: undefined })
    }
}
