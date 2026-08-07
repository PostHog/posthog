import { InternalPersonWithDistinctId } from '~/common/persons/repositories/person-repository'
import { InternalPerson } from '~/types'

import { PersonHogClient } from './client'
import { withRetry } from './grpc-retry'
import { GetOrCreatePersonEntry, PersonhogIdentityOperations } from './identity'
import { timedGrpc } from './metrics'
import { FoldedPersonUpdate } from './persons'

/**
 * Write-side person repository backed by personhog gRPC — the
 * counterpart to PersonHogPersonReadRepository, speaking personhog's own
 * vocabulary rather than the Postgres-shaped contract: folded updates
 * resolved by the leader, identity get-or-create with server-derived
 * uuids, and strong reads. The ingestion personhog store is its
 * consumer, and it grows a verb whenever the leader does. Deliberately
 * no deletes: the service's DeletePersons routes to the replica, a
 * direct Postgres write the leader's cache and changelog never see.
 *
 * Two endpoints sit behind it: person operations go through the router,
 * and identity get-or-create goes to the identity service's own
 * address — the router does not proxy the identity API.
 *
 * Every verb here is idempotent (folds, get-or-create, reads), so
 * transient-error retries are safe.
 */
export class PersonHogPersonWriteRepository {
    constructor(
        private grpcClient: PersonHogClient,
        private identity: PersonhogIdentityOperations,
        private clientLabel: string = 'unknown'
    ) {}

    fetchPersonsByDistinctIds(
        teamPersons: { teamId: number; distinctId: string }[],
        callerTag?: string,
        options?: { consistency?: 'strong' | 'eventual' }
    ): Promise<InternalPersonWithDistinctId[]> {
        const method = 'fetchPersonsByDistinctIds'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.persons.fetchPersonsByDistinctIds(teamPersons, callerTag, options)
                ),
            this.clientLabel,
            method
        )
    }

    /** Applies a folded diff under the leader's per-person lock and returns the person as written. */
    updatePersonProperties(
        update: FoldedPersonUpdate,
        callerTag?: string
    ): Promise<{ person: InternalPerson | null; updated: boolean }> {
        const method = 'updatePersonProperties'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.persons.updatePersonProperties(update, callerTag)
                ),
            this.clientLabel,
            method
        )
    }

    /**
     * Replica-routed and eventually consistent — acceptable for the
     * merge pre-checks that consume it today, revisit for read-your-write
     * once merge execution reaches this world.
     */
    getDistinctIdsForPersons(
        teamId: number,
        personIntIds: string[],
        limitPerPerson?: number,
        callerTag?: string
    ): Promise<Record<string, string[]>> {
        const method = 'getDistinctIdsForPersons'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.persons.getDistinctIdsForPersons(teamId, personIntIds, limitPerPerson, callerTag)
                ),
            this.clientLabel,
            method
        )
    }

    /** Resolution and creation in one idempotent verb; the uuid derives deterministically server-side. */
    getOrCreatePersonByDistinctId(
        entry: GetOrCreatePersonEntry,
        callerTag?: string
    ): Promise<{ person: InternalPerson; created: boolean }> {
        const method = 'getOrCreatePersonByDistinctId'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.identity.getOrCreatePersonByDistinctId(entry, callerTag)
                ),
            this.clientLabel,
            method
        )
    }
}
