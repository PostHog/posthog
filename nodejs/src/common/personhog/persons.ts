import { create } from '@bufbuild/protobuf'
import { Client, Code, ConnectError } from '@connectrpc/connect'

import { PersonHogService } from '~/common/generated/personhog/personhog/service/v1/service_pb'
import { TeamDistinctIdSchema } from '~/common/generated/personhog/personhog/types/v1/common_pb'
import {
    GetDistinctIdsForPersonsRequestSchema,
    GetPersonRequestSchema,
    GetPersonsByDistinctIdsRequestSchema,
    GetPersonsByUuidsRequestSchema,
    UpdatePersonPropertiesRequestSchema,
} from '~/common/generated/personhog/personhog/types/v1/person_pb'
import type { Person as ProtoPerson } from '~/common/generated/personhog/personhog/types/v1/person_pb'
import { InternalPersonWithDistinctId } from '~/common/persons/repositories/person-repository'
import { NoRowsUpdatedError } from '~/common/utils/utils'
import { Properties } from '~/plugin-scaffold'
import { InternalPerson } from '~/types'

import { epochMsToDateTime, eventualReadOptions, parseJsonBytes, strongReadOptions } from './client'

const textEncoder = new TextEncoder()

export function encodeJsonBytes(value: object): Uint8Array {
    return Object.keys(value).length === 0 ? new Uint8Array(0) : textEncoder.encode(JSON.stringify(value))
}

/**
 * The leader rejected an update at the person-properties size ceiling.
 * Carries what the transport layer knows; callers holding the person's
 * uuid and distinct id re-wrap it into their own error vocabulary.
 */
export class PersonhogPropertiesSizeError extends Error {
    constructor(
        message: string,
        public readonly teamId: number,
        public readonly personId: string
    ) {
        super(message)
        this.name = 'PersonhogPropertiesSizeError'
    }
}

/** A folded person-property update, resolved by the leader under the per-person lock. */
export interface FoldedPersonUpdate {
    teamId: number
    /** InternalPerson.id — the bigint row id as a string. */
    personId: string
    /** Representative event name; must not be one the leader's denylist filters out. */
    eventName: string
    setProperties: Properties
    /** Unresolved: the leader applies these only where the key is absent in authoritative state. */
    setOnceProperties: Properties
    unsetProperties: string[]
    /** OR-merged server-side; send true only — false and absence are equivalent no-ops. */
    isIdentified?: boolean
    /** Epoch milliseconds; max-merged server-side. */
    lastSeenAtMs?: number
}

export function protoPersonToDomain(proto: ProtoPerson): InternalPerson {
    return {
        id: String(proto.id),
        uuid: proto.uuid,
        team_id: Number(proto.teamId),
        properties: parseJsonBytes(proto.properties) ?? {},
        properties_last_updated_at: parseJsonBytes(proto.propertiesLastUpdatedAt) ?? {},
        properties_last_operation: parseJsonBytes(proto.propertiesLastOperation) ?? null,
        created_at: epochMsToDateTime(proto.createdAt),
        version: Number(proto.version),
        is_identified: proto.isIdentified,
        is_user_id: proto.isUserId != null ? (proto.isUserId ? 1 : 0) : null,
        last_seen_at: proto.lastSeenAt != null ? epochMsToDateTime(proto.lastSeenAt) : null,
    }
}

const PERSONHOG_BATCH_SIZE = 250

export class PersonHogPersonOperations {
    constructor(private client: Client<typeof PersonHogService>) {}

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: number; distinctId: string }[],
        callerTag?: string
    ): Promise<InternalPersonWithDistinctId[]> {
        if (teamPersons.length === 0) {
            return []
        }

        const results: InternalPersonWithDistinctId[] = []
        for (let i = 0; i < teamPersons.length; i += PERSONHOG_BATCH_SIZE) {
            const batch = teamPersons.slice(i, i + PERSONHOG_BATCH_SIZE)
            const response = await this.client.getPersonsByDistinctIds(
                create(GetPersonsByDistinctIdsRequestSchema, {
                    teamDistinctIds: batch.map(({ teamId, distinctId }) =>
                        create(TeamDistinctIdSchema, {
                            teamId: BigInt(teamId),
                            distinctId,
                        })
                    ),
                    readOptions: eventualReadOptions(),
                }),
                callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
            )

            for (const result of response.results) {
                if (result.person && result.key) {
                    const person = protoPersonToDomain(result.person) as InternalPersonWithDistinctId
                    person.distinct_id = result.key.distinctId
                    results.push(person)
                }
            }
        }
        return results
    }

    /**
     * Fetch up to ``limitPerPerson`` distinct_ids for each given int person_id.
     * Returns a record keyed by the int person_id (as a string, matching InternalPerson.id).
     * Callers that hold UUIDs should first convert via fetchPersonsByPersonIds to get int IDs.
     */
    async getDistinctIdsForPersons(
        teamId: number,
        personIntIds: string[],
        limitPerPerson?: number,
        callerTag?: string
    ): Promise<Record<string, string[]>> {
        if (personIntIds.length === 0) {
            return {}
        }

        const response = await this.client.getDistinctIdsForPersons(
            create(GetDistinctIdsForPersonsRequestSchema, {
                teamId: BigInt(teamId),
                personIds: personIntIds.map((id) => BigInt(id)),
                limitPerPerson: limitPerPerson != null ? BigInt(limitPerPerson) : undefined,
                readOptions: eventualReadOptions(),
            }),
            callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
        )

        const result: Record<string, string[]> = {}
        for (const pd of response.personDistinctIds) {
            result[String(pd.personId)] = pd.distinctIds.map((d) => d.distinctId)
        }
        return result
    }

    /**
     * Person state by id. Eventual reads go to the replica; strong reads
     * are routed to the partition's leader, whose cache the primary lags
     * by writer apply lag, so a caller that must observe its own writes
     * asks for strong. Returns null for a person that does not exist
     * (deleted, or merged away).
     */
    async fetchPersonById(
        teamId: number,
        personId: string,
        callerTag?: string,
        options?: { consistency?: 'strong' | 'eventual' }
    ): Promise<InternalPerson | null> {
        try {
            const response = await this.client.getPerson(
                create(GetPersonRequestSchema, {
                    teamId: BigInt(teamId),
                    personId: BigInt(personId),
                    readOptions: options?.consistency === 'strong' ? strongReadOptions() : eventualReadOptions(),
                }),
                callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
            )
            return response.person ? protoPersonToDomain(response.person) : null
        } catch (error) {
            if (error instanceof ConnectError && error.code === Code.NotFound) {
                return null
            }
            throw error
        }
    }

    /**
     * Apply a folded property update to one person. The leader merges the
     * diffs into authoritative state under the per-person lock and returns
     * the person as written, so the caller can publish it downstream.
     * Returns null person when the response carries none.
     */
    async updatePersonProperties(
        update: FoldedPersonUpdate,
        callerTag?: string
    ): Promise<{ person: InternalPerson | null; updated: boolean }> {
        try {
            const response = await this.client.updatePersonProperties(
                create(UpdatePersonPropertiesRequestSchema, {
                    teamId: BigInt(update.teamId),
                    personId: BigInt(update.personId),
                    eventName: update.eventName,
                    setProperties: encodeJsonBytes(update.setProperties),
                    setOnceProperties: encodeJsonBytes(update.setOnceProperties),
                    unsetProperties: update.unsetProperties,
                    isIdentified: update.isIdentified,
                    lastSeenAt: update.lastSeenAtMs != null ? BigInt(update.lastSeenAtMs) : undefined,
                }),
                callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
            )
            return {
                person: response.person ? protoPersonToDomain(response.person) : null,
                updated: response.updated,
            }
        } catch (error) {
            // Translate the personhog contract into domain errors here so
            // callers never handle gRPC codes: a missing person (deleted, or
            // merged away) surfaces as NoRowsUpdatedError, and the leader's
            // only InvalidArgument for a well-formed request is the
            // property-size ceiling. Everything else propagates untouched.
            if (error instanceof ConnectError) {
                if (error.code === Code.NotFound) {
                    throw new NoRowsUpdatedError(`Person ${update.personId} not found by personhog (deleted or merged)`)
                }
                if (error.code === Code.InvalidArgument && error.rawMessage.includes('size limit')) {
                    throw new PersonhogPropertiesSizeError(error.rawMessage, update.teamId, update.personId)
                }
            }
            throw error
        }
    }

    async fetchPersonsByPersonIds(
        teamPersons: { teamId: number; personId: string }[],
        callerTag?: string
    ): Promise<InternalPerson[]> {
        if (teamPersons.length === 0) {
            return []
        }

        const byTeam = new Map<number, string[]>()
        for (const { teamId, personId } of teamPersons) {
            const uuids = byTeam.get(teamId) ?? []
            uuids.push(personId)
            byTeam.set(teamId, uuids)
        }

        const allPersons = await Promise.all(
            [...byTeam].map(async ([teamId, uuids]) => {
                const batchResults: InternalPerson[] = []
                for (let i = 0; i < uuids.length; i += PERSONHOG_BATCH_SIZE) {
                    const batch = uuids.slice(i, i + PERSONHOG_BATCH_SIZE)
                    const response = await this.client.getPersonsByUuids(
                        create(GetPersonsByUuidsRequestSchema, {
                            teamId: BigInt(teamId),
                            uuids: batch,
                            readOptions: eventualReadOptions(),
                        }),
                        callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
                    )
                    batchResults.push(...response.persons.map(protoPersonToDomain))
                }
                return batchResults
            })
        )
        return allPersons.flat()
    }
}
