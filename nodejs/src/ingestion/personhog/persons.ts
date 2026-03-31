import { create } from '@bufbuild/protobuf'
import { Client } from '@connectrpc/connect'

import { PersonHogService } from '../../generated/personhog/personhog/service/v1/service_pb'
import { TeamDistinctIdSchema } from '../../generated/personhog/personhog/types/v1/common_pb'
import {
    GetPersonsByDistinctIdsRequestSchema,
    GetPersonsByUuidsRequestSchema,
} from '../../generated/personhog/personhog/types/v1/person_pb'
import type { Person as ProtoPerson } from '../../generated/personhog/personhog/types/v1/person_pb'
import { InternalPerson } from '../../types'
import { InternalPersonWithDistinctId } from '../../worker/ingestion/persons/repositories/person-repository'
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

export class PersonHogPersonOperations {
    constructor(private client: Client<typeof PersonHogService>) {}

    async fetchPersonsByDistinctIds(
        teamPersons: { teamId: number; distinctId: string }[]
    ): Promise<InternalPersonWithDistinctId[]> {
        if (teamPersons.length === 0) {
            return []
        }

        const response = await this.client.getPersonsByDistinctIds(
            create(GetPersonsByDistinctIdsRequestSchema, {
                teamDistinctIds: teamPersons.map(({ teamId, distinctId }) =>
                    create(TeamDistinctIdSchema, {
                        teamId: BigInt(teamId),
                        distinctId,
                    })
                ),
                readOptions: eventualReadOptions(),
            })
        )

        const results: InternalPersonWithDistinctId[] = []
        for (const result of response.results) {
            if (result.person && result.key) {
                const person = protoPersonToDomain(result.person) as InternalPersonWithDistinctId
                person.distinct_id = result.key.distinctId
                results.push(person)
            }
        }
        return results
    }

    async fetchPersonsByPersonIds(teamPersons: { teamId: number; personId: string }[]): Promise<InternalPerson[]> {
        if (teamPersons.length === 0) {
            return []
        }

        // Group by team_id since GetPersonsByUuids is a single-team RPC.
        // In practice callers (e.g. CDP PersonsManager) almost always pass a single team,
        // so multiple RPCs here is an edge case. If metrics show frequent multi-team batches,
        // consider adding a cross-team UUID RPC (similar to GetPersonsByDistinctIds).
        const byTeam = new Map<number, string[]>()
        for (const { teamId, personId } of teamPersons) {
            const uuids = byTeam.get(teamId) ?? []
            uuids.push(personId)
            byTeam.set(teamId, uuids)
        }

        const allPersons = await Promise.all(
            [...byTeam].map(async ([teamId, uuids]) => {
                const response = await this.client.getPersonsByUuids(
                    create(GetPersonsByUuidsRequestSchema, {
                        teamId: BigInt(teamId),
                        uuids,
                        readOptions: eventualReadOptions(),
                    })
                )
                return response.persons.map(protoPersonToDomain)
            })
        )
        return allPersons.flat()
    }
}
