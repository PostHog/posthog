import { PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { BatchProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { PipelineResult, ok } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { Person, Team } from '~/types'

export interface FetchPersonBatchStepInput {
    event: PluginEvent
    team: Team
}

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
 * `source` is the query-source tag forwarded to the repository for
 * per-pipeline observability.
 */
export function createFetchPersonBatchStep<T extends FetchPersonBatchStepInput>(
    personRepository: PersonReadRepository,
    source: string
): BatchProcessingStep<T, T & { person: Person | null }> {
    return async function fetchPersonBatchStep(inputs: T[]): Promise<PipelineResult<T & { person: Person | null }>[]> {
        if (inputs.length === 0) {
            return []
        }

        // Collect all team+distinct_id pairs that need lookup (skip empty distinct_ids)
        const lookups = inputs
            .filter((input) => input.event.distinct_id)
            .map((input) => ({ teamId: input.team.id, distinctId: input.event.distinct_id }))

        // Batch fetch all persons in a single query
        const persons = lookups.length > 0 ? await personRepository.fetchPersonsByDistinctIds(lookups, source) : []

        // Build lookup map
        const personMap = new Map(persons.map((p) => [personKey(p.team_id, p.distinct_id), p as Person]))

        // Map results back to inputs
        return inputs.map((input) => {
            const person = input.event.distinct_id
                ? (personMap.get(personKey(input.team.id, input.event.distinct_id)) ?? null)
                : null
            return ok({ ...input, person })
        })
    }
}
