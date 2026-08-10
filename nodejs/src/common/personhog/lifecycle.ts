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
     * produced the death documents. The saga is keyed by op_id and the
     * caller must supply one derived from the delete's identity: the
     * same id across retries attaches to the existing operation instead
     * of starting a new one, which keeps a retried delete from
     * misreading its own earlier success as not_found.
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
