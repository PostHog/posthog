import { InternalPersonWithDistinctId, PersonReadRepository } from '~/common/persons/repositories/person-repository'
import { InternalPerson, TeamId } from '~/types'

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
        const method = 'fetchPerson'
        const results = await withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.persons.fetchPersonsByDistinctIds([{ teamId, distinctId }], callerTag)
                ),
            this.clientLabel,
            method
        )
        return results.length > 0 ? results[0] : undefined
    }

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: TeamId; distinctId: string }[],
        callerTag?: string
    ): Promise<InternalPersonWithDistinctId[]> {
        const method = 'fetchPersonsByDistinctIds'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.persons.fetchPersonsByDistinctIds(teamPersons, callerTag)
                ),
            this.clientLabel,
            method
        )
    }

    async fetchPersonsByPersonIds(
        teamPersons: { teamId: TeamId; personId: string }[],
        callerTag?: string
    ): Promise<InternalPerson[]> {
        const method = 'fetchPersonsByPersonIds'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.persons.fetchPersonsByPersonIds(teamPersons, callerTag)
                ),
            this.clientLabel,
            method
        )
    }

    async fetchDistinctIdsForPersons(
        teamId: TeamId,
        personIntIds: string[],
        options?: { limitPerPerson?: number },
        callerTag?: string
    ): Promise<Record<string, string[]>> {
        const method = 'fetchDistinctIdsForPersons'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.persons.getDistinctIdsForPersons(
                        teamId,
                        personIntIds,
                        options?.limitPerPerson,
                        callerTag
                    )
                ),
            this.clientLabel,
            method
        )
    }
}
