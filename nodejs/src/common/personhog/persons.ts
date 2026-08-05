import { create } from '@bufbuild/protobuf'
import { Client } from '@connectrpc/connect'

import { PersonHogService } from '~/common/generated/personhog/personhog/service/v1/service_pb'
import { TeamDistinctIdSchema } from '~/common/generated/personhog/personhog/types/v1/common_pb'
import {
    GetDistinctIdsForPersonsRequestSchema,
    GetPersonsByDistinctIdsRequestSchema,
    GetPersonsByUuidsRequestSchema,
} from '~/common/generated/personhog/personhog/types/v1/person_pb'
import type { Person as ProtoPerson } from '~/common/generated/personhog/personhog/types/v1/person_pb'
import { InternalPersonWithDistinctId } from '~/common/persons/repositories/person-repository'
import { InternalPerson } from '~/types'

import { epochMsToDateTime, eventualReadOptions, parseJsonBytes } from './client'

function protoPersonToDomain(proto: ProtoPerson): InternalPerson {
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
