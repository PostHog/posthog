import { create } from '@bufbuild/protobuf'
import { Client } from '@connectrpc/connect'

import {
    DeletePersonOutcome,
    DeletePersonsRequestSchema,
    PersonHogLifecycle,
} from '~/common/generated/personhog/personhog/lifecycle/v1/lifecycle_pb'

export type PersonDeleteOutcome = 'deleted' | 'not_found' | 'skipped_conflict'

/**
 * Client wrapper for the lifecycle saga service. Co-served on the
 * identity server, so it shares the identity endpoint's transport; a
 * separate class because it is a separate gRPC service.
 */
export class PersonhogLifecycleOperations {
    constructor(private client: Client<typeof PersonHogLifecycle>) {}

    /**
     * Destroy persons through the durable delete saga. An OK response
     * means the sync-plane work is committed and the owning leaders have
     * produced the death documents. The saga is keyed by op_id, and the
     * caller must scope one to a single deletion attempt — never derive
     * it from the target rows, because deletion tombstones a row and
     * creation revives it with the same id, so a row-derived id would
     * attach a later independent delete to the completed operation and
     * leave the revived person live. Re-runs converge through the
     * outcomes instead: not_found means gone, skipped_conflict means a
     * live operation holds the person and the caller retries after it.
     */
    async deletePersons(
        teamId: number,
        personIds: string[],
        opId: string,
        callerTag?: string
    ): Promise<Map<string, PersonDeleteOutcome>> {
        if (personIds.length === 0) {
            return new Map()
        }
        const response = await this.client.deletePersons(
            create(DeletePersonsRequestSchema, {
                teamId: BigInt(teamId),
                personIds: personIds.map((id) => BigInt(id)),
                opId,
            }),
            callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
        )
        const outcomes = new Map<string, PersonDeleteOutcome>()
        for (const result of response.results) {
            const outcome =
                result.outcome === DeletePersonOutcome.DELETED
                    ? 'deleted'
                    : result.outcome === DeletePersonOutcome.NOT_FOUND
                      ? 'not_found'
                      : 'skipped_conflict'
            outcomes.set(String(result.personId), outcome)
        }
        return outcomes
    }
}
