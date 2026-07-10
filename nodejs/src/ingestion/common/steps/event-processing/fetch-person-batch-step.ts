import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { ChunkProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { Person, Team } from '~/types'

export interface FetchPersonBatchStepInput {
    event: PluginEvent
    team: Team
}

// Query name forwarded to the repository (the "what query" half of the personhog
// read tag). The "who" half — pipeline/lane — is the repository's client label.
const QUERY_NAME = 'fetch-person-batch-step'

function personKey(teamId: number, distinctId: string): string {
    return `${teamId}:${distinctId}`
}

/**
 * Creates a batch step that fetches person data for read-only pipelines
 * (error tracking, AI).
 *
 * This is a read-only step that fetches person data from the database
 * and passes it downstream. It does not create or update persons, and
 * does not modify event properties.
 *
 * The person object is used by downstream steps (createCreateEventStep)
 * to set the top-level person_id, person_properties, and person_created_at
 * fields on the ClickHouse event.
 *
 * This is a batch step to avoid N+1 queries when processing multiple events.
 * The per-pipeline identity (client name) comes from the repository's client
 * label; this step only tags the query.
 */
export function createFetchPersonBatchStep<T extends FetchPersonBatchStepInput>(
    personRepository: PersonReadRepository
): ChunkProcessingStep<T, T & { person: Person | undefined }> {
    return async function fetchPersonBatchStep(
        inputs: T[]
    ): Promise<PipelineResult<T & { person: Person | undefined }>[]> {
        if (inputs.length === 0) {
            return []
        }

        // Collect all team+distinct_id pairs that need lookup (skip empty distinct_ids)
        const lookups = inputs
            .filter((input) => input.event.distinct_id)
            .map((input) => ({ teamId: input.team.id, distinctId: input.event.distinct_id }))

        // Batch fetch all persons in a single query
        const persons = lookups.length > 0 ? await personRepository.fetchPersonsByDistinctIds(lookups, QUERY_NAME) : []

        // Build lookup map
        const personMap = new Map(persons.map((p) => [personKey(p.team_id, p.distinct_id), p as Person]))

        // Map results back to inputs. `undefined` (not `null`) for not-found, matching
        // the optional `person?` that createCreateEventStep / createEvent expect.
        return inputs.map((input) => {
            const person = input.event.distinct_id
                ? personMap.get(personKey(input.team.id, input.event.distinct_id))
                : undefined
            return ok({ ...input, person })
        })
    }
}
