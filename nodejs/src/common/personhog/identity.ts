import { create } from '@bufbuild/protobuf'
import { Client, Code, ConnectError } from '@connectrpc/connect'

import {
    GetDistinctIdsForPersonsRequestSchema,
    GetOrCreatePersonByDistinctIdRequestSchema,
    GetPersonsByDistinctIdsRequestSchema,
    PersonHogIdentity,
} from '~/common/generated/personhog/personhog/identity/v1/identity_pb'
import { PersonPropertiesSizeViolationError } from '~/common/persons/repositories/person-repository'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson } from '~/types'

import { encodeJsonBytes, protoPersonToDomain } from './persons'

/**
 * A single get-or-create key: resolve distinct_id within team_id,
 * creating a person stub when absent. The properties and scalars apply
 * on the creation branch only; an existing person takes its ops through
 * the normal update path. The person UUID derives deterministically from
 * team_id:distinct_id on the identity service's side; no id is supplied
 * here.
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

/** The identity service rejects batches above this; chunk client-side. */
const IDENTITY_BATCH_SIZE = 250

export interface DistinctIdKey {
    teamId: number
    distinctId: string
}

/**
 * The identity service's client wrapper: proto encoding and domain
 * decoding for distinct-id resolution, expansion, and person stub
 * creation. Callers never see proto types or gRPC codes through this
 * surface.
 */
export class PersonhogIdentityOperations {
    constructor(private client: Client<typeof PersonHogIdentity>) {}

    /**
     * Resolve-only counterpart of get-or-create: primary-backed
     * resolution, never creates. Results come back in request order;
     * a null person means the distinct id resolves to no live person.
     */
    async getPersonsByDistinctIds(
        keys: DistinctIdKey[],
        callerTag?: string
    ): Promise<{ teamId: number; distinctId: string; person: InternalPerson | null }[]> {
        if (keys.length === 0) {
            return []
        }
        const out: { teamId: number; distinctId: string; person: InternalPerson | null }[] = []
        for (let i = 0; i < keys.length; i += IDENTITY_BATCH_SIZE) {
            const chunk = keys.slice(i, i + IDENTITY_BATCH_SIZE)
            const response = await this.client.getPersonsByDistinctIds(
                create(GetPersonsByDistinctIdsRequestSchema, {
                    keys: chunk.map((key) => ({
                        teamId: BigInt(key.teamId),
                        distinctId: key.distinctId,
                    })),
                }),
                callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
            )
            for (const result of response.results) {
                out.push({
                    teamId: Number(result.teamId),
                    distinctId: result.distinctId,
                    person: result.person ? protoPersonToDomain(result.person) : null,
                })
            }
        }
        return out
    }

    /**
     * Person-id to distinct-ids expansion on the primary — the strong
     * twin of the router RPC of the same name. Grouped per person id;
     * with a limit, identified ids survive the cut.
     */
    async getDistinctIdsForPersons(
        teamId: number,
        personIds: string[],
        limitPerPerson?: number,
        callerTag?: string
    ): Promise<Record<string, string[]>> {
        if (personIds.length === 0) {
            return {}
        }
        const byPerson: Record<string, string[]> = {}
        for (let i = 0; i < personIds.length; i += IDENTITY_BATCH_SIZE) {
            const chunk = personIds.slice(i, i + IDENTITY_BATCH_SIZE)
            const response = await this.client.getDistinctIdsForPersons(
                create(GetDistinctIdsForPersonsRequestSchema, {
                    teamId: BigInt(teamId),
                    personIds: chunk.map((id) => BigInt(id)),
                    limitPerPerson: limitPerPerson != null ? BigInt(limitPerPerson) : undefined,
                }),
                callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
            )
            for (const group of response.personDistinctIds) {
                byPerson[String(group.personId)] = group.distinctIds.map((d) => d.distinctId)
            }
        }
        return byPerson
    }

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
            // create service already handles, which emits the customer
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
