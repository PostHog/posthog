import { InternalPerson, TeamId } from '../../types'
import {
    InternalPersonWithDistinctId,
    PersonReadRepository,
} from '../../worker/ingestion/persons/repositories/person-repository'
import { PersonHogClient } from './client'
import { withRetry } from './grpc-retry'
import { timedGrpc } from './metrics'

/**
 * Read-only person repository backed by personhog gRPC. No Postgres
 * dependency — all reads go through personhog with automatic retries
 * on transient errors.
 */
export class PersonHogPersonReadRepository implements PersonReadRepository {
    constructor(
        private grpcClient: PersonHogClient,
        private clientLabel: string = 'unknown'
    ) {}

    async fetchPerson(teamId: number, distinctId: string, callerTag?: string): Promise<InternalPerson | undefined> {
        const results = await withRetry('PersonHogPersonReadRepository', () =>
            timedGrpc(this.clientLabel, 'fetchPerson', () =>
                this.grpcClient.persons.fetchPersonsByDistinctIds([{ teamId, distinctId }], callerTag)
            )
        )
        return results.length > 0 ? results[0] : undefined
    }

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[],
        callerTag?: string
    ): Promise<InternalPersonWithDistinctId[]> {
        return withRetry('PersonHogPersonReadRepository', () =>
            timedGrpc(this.clientLabel, 'fetchPersonsByDistinctIds', () =>
                this.grpcClient.persons.fetchPersonsByDistinctIds(teamPersons, callerTag)
            )
        )
    }

    async fetchPersonsByPersonIds(
        teamPersons: { teamId: TeamId; personId: string }[],
        callerTag?: string
    ): Promise<InternalPerson[]> {
        return withRetry('PersonHogPersonReadRepository', () =>
            timedGrpc(this.clientLabel, 'fetchPersonsByPersonIds', () =>
                this.grpcClient.persons.fetchPersonsByPersonIds(teamPersons, callerTag)
            )
        )
    }

    async fetchDistinctIdsForPersons(
        teamId: TeamId,
        personIntIds: string[],
        options?: { limitPerPerson?: number },
        callerTag?: string
    ): Promise<Record<string, string[]>> {
        return withRetry('PersonHogPersonReadRepository', () =>
            timedGrpc(this.clientLabel, 'fetchDistinctIdsForPersons', () =>
                this.grpcClient.persons.getDistinctIdsForPersons(
                    teamId,
                    personIntIds,
                    options?.limitPerPerson,
                    callerTag
                )
            )
        )
    }
}
