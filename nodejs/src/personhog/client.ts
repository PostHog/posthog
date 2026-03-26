import { create } from '@bufbuild/protobuf'
import { createClient } from '@connectrpc/connect'
import { createGrpcTransport } from '@connectrpc/connect-node'
import { DateTime } from 'luxon'

import { PersonHogService } from '../generated/personhog/personhog/service/v1/service_pb'
import { ConsistencyLevel } from '../generated/personhog/personhog/types/v1/common_pb'
import { GroupKeySchema, ReadOptionsSchema } from '../generated/personhog/personhog/types/v1/common_pb'
import {
    GetGroupRequestSchema,
    GetGroupTypeMappingsByProjectIdsRequestSchema,
    GetGroupTypeMappingsByTeamIdsRequestSchema,
    GetGroupsBatchRequestSchema,
} from '../generated/personhog/personhog/types/v1/group_pb'
import type { Group as ProtoGroup } from '../generated/personhog/personhog/types/v1/group_pb'
import { Group as DomainGroup, GroupTypeIndex } from '../types'
import { parseJSON } from '../utils/json-parse'

const textDecoder = new TextDecoder()

function parseJsonBytes(bytes: Uint8Array): any {
    if (bytes.length === 0) {
        return null
    }
    return parseJSON(textDecoder.decode(bytes))
}

function epochMsToDateTime(epochMs: bigint): DateTime {
    return DateTime.fromMillis(Number(epochMs), { zone: 'utc' })
}

function protoGroupToDomain(proto: ProtoGroup): DomainGroup {
    return {
        id: Number(proto.id),
        team_id: Number(proto.teamId),
        group_type_index: proto.groupTypeIndex as GroupTypeIndex,
        group_key: proto.groupKey,
        group_properties: parseJsonBytes(proto.groupProperties) ?? {},
        properties_last_updated_at: parseJsonBytes(proto.propertiesLastUpdatedAt) ?? {},
        properties_last_operation: parseJsonBytes(proto.propertiesLastOperation) ?? {},
        created_at: epochMsToDateTime(proto.createdAt),
        version: Number(proto.version),
    }
}

function eventualReadOptions() {
    return create(ReadOptionsSchema, { consistency: ConsistencyLevel.EVENTUAL })
}

export interface PersonHogClientConfig {
    addr: string
    useTls?: boolean
    timeoutMs?: number
    readMaxBytes?: number
    writeMaxBytes?: number
    pingIntervalMs?: number
    pingTimeoutMs?: number
    pingIdleConnection?: boolean
}

export class PersonHogClient {
    private client: ReturnType<typeof createClient<typeof PersonHogService>>

    constructor(config: PersonHogClientConfig) {
        const scheme = config.useTls ? 'https' : 'http'
        const transport = createGrpcTransport({
            baseUrl: `${scheme}://${config.addr}`,
            defaultTimeoutMs: config.timeoutMs ?? 5_000,
            readMaxBytes: config.readMaxBytes ?? 128 * 1024 * 1024,
            writeMaxBytes: config.writeMaxBytes ?? 4 * 1024 * 1024,
            pingIntervalMs: config.pingIntervalMs ?? 30_000,
            pingTimeoutMs: config.pingTimeoutMs ?? 5_000,
            pingIdleConnection: config.pingIdleConnection ?? true,
        })
        this.client = createClient(PersonHogService, transport)
    }

    async fetchGroup(teamId: number, groupTypeIndex: number, groupKey: string): Promise<DomainGroup | undefined> {
        const response = await this.client.getGroup(
            create(GetGroupRequestSchema, {
                teamId: BigInt(teamId),
                groupTypeIndex,
                groupKey,
                readOptions: eventualReadOptions(),
            })
        )
        return response.group ? protoGroupToDomain(response.group) : undefined
    }

    async fetchGroupsByKeys(
        teamIds: number[],
        groupTypeIndexes: number[],
        groupKeys: string[]
    ): Promise<
        {
            team_id: number
            group_type_index: GroupTypeIndex
            group_key: string
            group_properties: Record<string, any>
        }[]
    > {
        if (teamIds.length === 0) {
            return []
        }

        const response = await this.client.getGroupsBatch(
            create(GetGroupsBatchRequestSchema, {
                keys: teamIds.map((teamId, i) =>
                    create(GroupKeySchema, {
                        teamId: BigInt(teamId),
                        groupTypeIndex: groupTypeIndexes[i],
                        groupKey: groupKeys[i],
                    })
                ),
                readOptions: eventualReadOptions(),
            })
        )

        const results: {
            team_id: number
            group_type_index: GroupTypeIndex
            group_key: string
            group_properties: Record<string, any>
        }[] = []

        for (const result of response.results) {
            if (result.group && result.key) {
                results.push({
                    team_id: Number(result.key.teamId),
                    group_type_index: result.key.groupTypeIndex as GroupTypeIndex,
                    group_key: result.key.groupKey,
                    group_properties: parseJsonBytes(result.group.groupProperties) ?? {},
                })
            }
        }

        return results
    }

    async fetchGroupTypesByTeamIds(
        teamIds: number[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        if (teamIds.length === 0) {
            return {}
        }

        const response = await this.client.getGroupTypeMappingsByTeamIds(
            create(GetGroupTypeMappingsByTeamIdsRequestSchema, {
                teamIds: teamIds.map(BigInt),
                readOptions: eventualReadOptions(),
            })
        )

        const result: Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]> = {}
        for (const entry of response.results) {
            result[entry.key.toString()] = entry.mappings.map((m) => ({
                group_type: m.groupType,
                group_type_index: m.groupTypeIndex as GroupTypeIndex,
            }))
        }
        return result
    }

    async fetchGroupTypesByProjectIds(
        projectIds: number[]
    ): Promise<Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]>> {
        if (projectIds.length === 0) {
            return {}
        }

        const response = await this.client.getGroupTypeMappingsByProjectIds(
            create(GetGroupTypeMappingsByProjectIdsRequestSchema, {
                projectIds: projectIds.map(BigInt),
                readOptions: eventualReadOptions(),
            })
        )

        const result: Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]> = {}
        for (const entry of response.results) {
            result[entry.key.toString()] = entry.mappings.map((m) => ({
                group_type: m.groupType,
                group_type_index: m.groupTypeIndex as GroupTypeIndex,
            }))
        }
        return result
    }
}
