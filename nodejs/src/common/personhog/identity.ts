import { create } from '@bufbuild/protobuf'
import { Client, Code, ConnectError } from '@connectrpc/connect'

import {
    GetOrCreatePersonByDistinctIdRequestSchema,
    PersonHogIdentity,
} from '~/common/generated/personhog/personhog/identity/v1/identity_pb'
import { PersonPropertiesSizeViolationError } from '~/common/persons/repositories/person-repository'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson } from '~/types'

import { encodeJsonBytes, protoPersonToDomain } from './persons'

/**
 * A single get-or-create key: resolve distinct_id within team_id, creating
 * a person stub when absent. The properties and scalars apply on the
 * creation branch only — for an existing person the caller sends its ops
 * through the normal update path instead. The person UUID derives
 * deterministically from team_id:distinct_id on the identity service's
 * side; no id is supplied here.
 */
export interface GetOrCreatePersonEntry {
    teamId: number
    distinctId: string
    /** Additional distinct ids mapped to the person on the creation branch. */
    extraDistinctIds?: string[]
    /** The event name that triggered this call, forwarded to the leader on creation. */
    eventName: string
    setProperties?: Properties
    setOnceProperties?: Properties
    /** Person created_at on the creation branch, epoch milliseconds. */
    createdAtMs: number
    isIdentified?: boolean
}

/**
 * The identity service's client wrapper: proto encoding and domain
 * decoding for distinct-id resolution and person stub creation. Callers
 * never see proto types or gRPC codes through this surface.
 */
export class PersonhogIdentityOperations {
    constructor(private client: Client<typeof PersonHogIdentity>) {}

    /**
     * Resolves the distinct id to its person, creating a stub when
     * absent. `created` means the stub row is committed in Postgres and
     * any initial properties are durable in the leader's changelog.
     */
    async getOrCreatePersonByDistinctId(
        entry: GetOrCreatePersonEntry,
        callerTag?: string
    ): Promise<{ person: InternalPerson; created: boolean }> {
        try {
            const response = await this.client.getOrCreatePersonByDistinctId(
                create(GetOrCreatePersonByDistinctIdRequestSchema, {
                    entry: {
                        teamId: BigInt(entry.teamId),
                        distinctId: entry.distinctId,
                        extraDistinctIds: entry.extraDistinctIds ?? [],
                        eventName: entry.eventName,
                        setProperties: encodeJsonBytes(entry.setProperties ?? {}),
                        setOnceProperties: encodeJsonBytes(entry.setOnceProperties ?? {}),
                        createdAt: BigInt(entry.createdAtMs),
                        isIdentified: entry.isIdentified ?? false,
                    },
                }),
                callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
            )
            if (!response.person) {
                throw new Error(
                    `identity get-or-create returned no person for team ${entry.teamId} distinct_id ${entry.distinctId}`
                )
            }
            return { person: protoPersonToDomain(response.person), created: response.created }
        } catch (error) {
            // A size rejection must surface as the domain error the
            // create service already handles — it emits the customer
            // ingestion warning and stops retrying. Left untranslated,
            // the raw gRPC error matches no non-retriable class and the
            // batch redelivers the same oversized event forever.
            if (error instanceof ConnectError && error.code === Code.InvalidArgument) {
                if (error.rawMessage.includes('size limit')) {
                    throw new PersonPropertiesSizeViolationError(
                        error.rawMessage,
                        entry.teamId,
                        undefined,
                        entry.distinctId
                    )
                }
            }
            throw error
        }
    }
}
