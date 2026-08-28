import { InternalPerson } from '~/types'

import { PersonHogClient } from './client'
import { withRetry } from './grpc-retry'
import {
    DistinctIdKey,
    GetOrCreatePersonEntry,
    MergeSagaRequest,
    MergeSagaResult,
    PersonhogIdentityOperations,
} from './identity'
import { timedGrpc } from './metrics'
import { FoldedPersonUpdate } from './persons'

/**
 * Write-side person repository backed by personhog gRPC, the
 * counterpart to PersonHogPersonReadRepository speaking personhog's own
 * vocabulary rather than the Postgres-shaped contract. No verb touches
 * the replica: resolution goes to the identity service (primary), person
 * state and folded updates go through the router to the partition's
 * leader.
 *
 * Two endpoints sit behind it: person operations go through the router;
 * identity resolution and get-or-create go to the identity server's own
 * address. The router proxies neither API.
 *
 * Every verb is idempotent (folds, get-or-create, reads), so
 * transient-error retries are safe.
 */
export class PersonHogPersonWriteRepository {
    constructor(
        private grpcClient: PersonHogClient,
        private identity: PersonhogIdentityOperations,
        private clientLabel: string = 'unknown'
    ) {}

    /**
     * Primary-backed distinct-id resolution; never creates. Results in
     * request order, null person for an unresolved key. State freshness
     * is writer-applied — callers that need the leader's view fetch the
     * person by id afterwards.
     */
    resolvePersonsByDistinctIds(
        keys: DistinctIdKey[],
        callerTag?: string
    ): Promise<{ teamId: number; distinctId: string; person: InternalPerson | null }[]> {
        const method = 'resolvePersonsByDistinctIds'
        return withRetry(
            () => timedGrpc(this.clientLabel, method, () => this.identity.getPersonsByDistinctIds(keys, callerTag)),
            this.clientLabel,
            method
        )
    }

    /** Leader-routed strong person read; null when deleted or merged away. */
    fetchPersonById(teamId: number, personId: string, callerTag?: string): Promise<InternalPerson | null> {
        const method = 'fetchPersonById'
        return withRetry(
            () =>
                timedGrpc(this.clientLabel, method, () =>
                    this.grpcClient.persons.fetchPersonById(teamId, personId, callerTag, {
                        consistency: 'strong',
                    })
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

    /** Primary-backed expansion via identity — the merge pre-checks read their own writes. */
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
                    this.identity.getDistinctIdsForPersons(teamId, personIntIds, limitPerPerson, callerTag)
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

    /**
     * Runs the identity service's merge saga to completion. Safe under
     * retry: the op id in the request dedupes, so a retried call returns
     * the recorded outcome instead of merging again.
     */
    mergePersons(request: MergeSagaRequest, callerTag?: string): Promise<MergeSagaResult> {
        const method = 'mergePersons'
        return withRetry(
            () => timedGrpc(this.clientLabel, method, () => this.identity.mergePersons(request, callerTag)),
            this.clientLabel,
            method
        )
    }
}
