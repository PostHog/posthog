import { create } from '@bufbuild/protobuf'
import { Client } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogService } from '~/common/generated/personhog/personhog/service/v1/service_pb'
import { GroupKeySchema } from '~/common/generated/personhog/personhog/types/v1/common_pb'
import {
    GetGroupRequestSchema,
    GetGroupTypeMappingsByProjectIdsRequestSchema,
    GetGroupTypeMappingsByTeamIdsRequestSchema,
    GetGroupsBatchRequestSchema,
} from '~/common/generated/personhog/personhog/types/v1/group_pb'
import type { Group as ProtoGroup } from '~/common/generated/personhog/personhog/types/v1/group_pb'
import { Group as DomainGroup, GroupTypeIndex } from '~/types'

import { epochMsToDateTime, eventualReadOptions, parseJsonBytes } from './client'

const PERSONHOG_BATCH_SIZE = 100
const VALID_GROUP_TYPE_INDEXES = new Set<number>([0, 1, 2, 3, 4])

function toGroupTypeIndex(value: number): GroupTypeIndex {
    if (!VALID_GROUP_TYPE_INDEXES.has(value)) {
        throw new Error(`Invalid group type index: ${value}`)
    }
    return value as GroupTypeIndex
}

function protoGroupToDomain(proto: ProtoGroup): DomainGroup {
    return {
        id: Number(proto.id),
        team_id: Number(proto.teamId),
        group_type_index: toGroupTypeIndex(proto.groupTypeIndex),
        group_key: proto.groupKey,
        group_properties: parseJsonBytes(proto.groupProperties) ?? {},
        properties_last_updated_at: parseJsonBytes(proto.propertiesLastUpdatedAt) ?? {},
        properties_last_operation: parseJsonBytes(proto.propertiesLastOperation) ?? {},
        created_at: epochMsToDateTime(proto.createdAt),
        version: Number(proto.version),
    }
}

export class PersonHogGroupOperations {
    constructor(private client: Client<typeof PersonHogService>) {}

    async fetchGroup(
        teamId: number,
        groupTypeIndex: number,
        groupKey: string,
        callerTag?: string
    ): Promise<DomainGroup | undefined> {
        const response = await this.client.getGroup(
            create(GetGroupRequestSchema, {
                teamId: BigInt(teamId),
                groupTypeIndex,
                groupKey,
                readOptions: eventualReadOptions(),
            }),
            callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
        )
        return response.group ? protoGroupToDomain(response.group) : undefined
    }

    async fetchGroupsByKeys(
        teamIds: number[],
        groupTypeIndexes: number[],
        groupKeys: string[],
        callerTag?: string
    ): Promise<
        {
            team_id: number
            group_type_index: GroupTypeIndex
            group_key: string
            group_properties: Record<string, any>
            created_at: DateTime
            version: number
        }[]
    > {
        if (teamIds.length === 0) {
            return []
        }

        const results: {
            team_id: number
            group_type_index: GroupTypeIndex
            group_key: string
            group_properties: Record<string, any>
            created_at: DateTime
            version: number
        }[] = []

        for (let i = 0; i < teamIds.length; i += PERSONHOG_BATCH_SIZE) {
            const batchTeamIds = teamIds.slice(i, i + PERSONHOG_BATCH_SIZE)
            const batchGroupTypeIndexes = groupTypeIndexes.slice(i, i + PERSONHOG_BATCH_SIZE)
            const batchGroupKeys = groupKeys.slice(i, i + PERSONHOG_BATCH_SIZE)

            const response = await this.client.getGroupsBatch(
                create(GetGroupsBatchRequestSchema, {
                    keys: batchTeamIds.map((teamId, j) =>
                        create(GroupKeySchema, {
                            teamId: BigInt(teamId),
                            groupTypeIndex: batchGroupTypeIndexes[j],
                            groupKey: batchGroupKeys[j],
                        })
                    ),
                    readOptions: eventualReadOptions(),
                }),
                callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
            )

            for (const result of response.results) {
                if (result.group && result.key) {
                    results.push({
                        team_id: Number(result.key.teamId),
                        group_type_index: toGroupTypeIndex(result.key.groupTypeIndex),
                        group_key: result.key.groupKey,
                        group_properties: parseJsonBytes(result.group.groupProperties) ?? {},
                        created_at: epochMsToDateTime(result.group.createdAt),
                        version: Number(result.group.version),
                    })
                }
            }
        }

        return results
    }

    async fetchGroupTypesByTeamIds(
        teamIds: number[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        if (teamIds.length === 0) {
            return {}
        }

        const response = await this.client.getGroupTypeMappingsByTeamIds(
            create(GetGroupTypeMappingsByTeamIdsRequestSchema, {
                teamIds: teamIds.map(BigInt),
                readOptions: eventualReadOptions(),
            }),
            callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
        )

        const result: Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]> = {}
        for (const entry of response.results) {
            result[entry.key.toString()] = entry.mappings.map((m) => ({
                group_type: m.groupType,
                group_type_index: toGroupTypeIndex(m.groupTypeIndex),
            }))
        }
        return result
    }

    async fetchGroupTypesByProjectIds(
        projectIds: number[],
        callerTag?: string
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        if (projectIds.length === 0) {
            return {}
        }

        const response = await this.client.getGroupTypeMappingsByProjectIds(
            create(GetGroupTypeMappingsByProjectIdsRequestSchema, {
                projectIds: projectIds.map(BigInt),
                readOptions: eventualReadOptions(),
            }),
            callerTag ? { headers: { 'x-caller-tag': callerTag } } : undefined
        )

        const result: Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]> = {}
        for (const entry of response.results) {
            result[entry.key.toString()] = entry.mappings.map((m) => ({
                group_type: m.groupType,
                group_type_index: toGroupTypeIndex(m.groupTypeIndex),
            }))
        }
        return result
    }
}
