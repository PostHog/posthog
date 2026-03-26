import { create } from '@bufbuild/protobuf'
import { DateTime } from 'luxon'

import { ConsistencyLevel } from '../generated/personhog/personhog/types/v1/common_pb'
import { GroupKeySchema } from '../generated/personhog/personhog/types/v1/common_pb'
import {
    GetGroupResponseSchema,
    GetGroupsBatchResponseSchema,
    GroupSchema,
    GroupTypeMappingSchema,
    GroupTypeMappingsBatchResponseSchema,
    GroupTypeMappingsByKeySchema,
    GroupWithKeySchema,
} from '../generated/personhog/personhog/types/v1/group_pb'
import { PersonHogClient } from './client'

const textEncoder = new TextEncoder()
function jsonBytes(obj: any): Uint8Array {
    return textEncoder.encode(JSON.stringify(obj))
}

const mockRpcClient = {
    getGroup: jest.fn(),
    getGroupsBatch: jest.fn(),
    getGroupTypeMappingsByTeamIds: jest.fn(),
    getGroupTypeMappingsByProjectIds: jest.fn(),
}

jest.mock('@connectrpc/connect', () => ({
    createClient: () => mockRpcClient,
}))
jest.mock('@connectrpc/connect-node', () => ({
    createGrpcTransport: () => ({}),
}))

describe('PersonHogClient', () => {
    let client: PersonHogClient

    const CREATED_AT_MS = BigInt(DateTime.fromISO('2024-06-15T12:00:00.000Z', { zone: 'utc' }).toMillis())

    beforeEach(() => {
        client = new PersonHogClient({ addr: 'localhost:50051' })
    })

    // Helper that builds a plain-object proto group (for basic conversion tests)
    function makePlainProtoGroup(
        overrides: Partial<{
            id: bigint
            teamId: bigint
            groupTypeIndex: number
            groupKey: string
            groupProperties: Uint8Array
            createdAt: bigint
            propertiesLastUpdatedAt: Uint8Array
            propertiesLastOperation: Uint8Array
            version: bigint
        }> = {}
    ) {
        return {
            id: BigInt(42),
            teamId: BigInt(1),
            groupTypeIndex: 0,
            groupKey: 'acme-corp',
            groupProperties: jsonBytes({ name: 'Acme Corp', industry: 'tech' }),
            createdAt: CREATED_AT_MS,
            propertiesLastUpdatedAt: jsonBytes({ name: '2024-06-15T12:00:00Z' }),
            propertiesLastOperation: jsonBytes({ name: 'set' }),
            version: BigInt(3),
            ...overrides,
        }
    }

    // Helper that builds a real protobuf Message using the generated schema
    function makeRealProtoGroup(
        overrides: Partial<{
            id: bigint
            teamId: bigint
            groupTypeIndex: number
            groupKey: string
            groupProperties: Uint8Array
            createdAt: bigint
            propertiesLastUpdatedAt: Uint8Array
            propertiesLastOperation: Uint8Array
            version: bigint
        }> = {}
    ) {
        return create(GroupSchema, {
            id: BigInt(42),
            teamId: BigInt(1),
            groupTypeIndex: 0,
            groupKey: 'acme-corp',
            groupProperties: jsonBytes({ name: 'Acme Corp', industry: 'tech' }),
            createdAt: CREATED_AT_MS,
            propertiesLastUpdatedAt: jsonBytes({ name: '2024-06-15T12:00:00Z' }),
            propertiesLastOperation: jsonBytes({ name: 'set' }),
            version: BigInt(3),
            ...overrides,
        })
    }

    describe('fetchGroup', () => {
        it('converts proto group to domain group', async () => {
            mockRpcClient.getGroup.mockResolvedValue({ group: makePlainProtoGroup() })

            const result = await client.fetchGroup(1, 0, 'acme-corp')

            expect(result).toEqual({
                id: 42,
                team_id: 1,
                group_type_index: 0,
                group_key: 'acme-corp',
                group_properties: { name: 'Acme Corp', industry: 'tech' },
                properties_last_updated_at: { name: '2024-06-15T12:00:00Z' },
                properties_last_operation: { name: 'set' },
                created_at: DateTime.fromISO('2024-06-15T12:00:00.000Z', { zone: 'utc' }),
                version: 3,
            })
        })

        it('returns undefined when group is not found', async () => {
            mockRpcClient.getGroup.mockResolvedValue({})

            const result = await client.fetchGroup(1, 0, 'nonexistent')

            expect(result).toBeUndefined()
        })

        it('handles empty JSON bytes as empty objects', async () => {
            mockRpcClient.getGroup.mockResolvedValue({
                group: makePlainProtoGroup({
                    groupProperties: new Uint8Array(0),
                    propertiesLastUpdatedAt: new Uint8Array(0),
                    propertiesLastOperation: new Uint8Array(0),
                }),
            })

            const result = await client.fetchGroup(1, 0, 'empty-props')

            expect(result).toMatchObject({
                group_properties: {},
                properties_last_updated_at: {},
                properties_last_operation: {},
            })
        })

        it('converts bigint fields to numbers', async () => {
            mockRpcClient.getGroup.mockResolvedValue({
                group: makePlainProtoGroup({
                    id: BigInt(999),
                    teamId: BigInt(77),
                    version: BigInt(15),
                }),
            })

            const result = await client.fetchGroup(77, 0, 'acme-corp')

            expect(result).toMatchObject({
                id: 999,
                team_id: 77,
                version: 15,
            })
        })
    })

    describe('fetchGroupsByKeys', () => {
        it('converts batch proto response to domain objects', async () => {
            mockRpcClient.getGroupsBatch.mockResolvedValue({
                results: [
                    {
                        key: { teamId: BigInt(1), groupTypeIndex: 0, groupKey: 'acme' },
                        group: makePlainProtoGroup({ groupProperties: jsonBytes({ name: 'Acme' }) }),
                    },
                    {
                        key: { teamId: BigInt(2), groupTypeIndex: 1, groupKey: 'globex' },
                        group: makePlainProtoGroup({ groupProperties: jsonBytes({ name: 'Globex' }) }),
                    },
                ],
            })

            const result = await client.fetchGroupsByKeys([1, 2], [0, 1], ['acme', 'globex'])

            expect(result).toEqual([
                { team_id: 1, group_type_index: 0, group_key: 'acme', group_properties: { name: 'Acme' } },
                { team_id: 2, group_type_index: 1, group_key: 'globex', group_properties: { name: 'Globex' } },
            ])
        })

        it('skips results with missing group or key', async () => {
            mockRpcClient.getGroupsBatch.mockResolvedValue({
                results: [
                    { key: { teamId: BigInt(1), groupTypeIndex: 0, groupKey: 'found' }, group: makePlainProtoGroup() },
                    { key: { teamId: BigInt(1), groupTypeIndex: 0, groupKey: 'no-group' } },
                    { group: makePlainProtoGroup() },
                ],
            })

            const result = await client.fetchGroupsByKeys([1, 1, 1], [0, 0, 0], ['found', 'no-group', 'no-key'])

            expect(result).toHaveLength(1)
            expect(result[0].group_key).toBe('found')
        })

        it('returns empty array for empty input without calling gRPC', async () => {
            const result = await client.fetchGroupsByKeys([], [], [])

            expect(result).toEqual([])
            expect(mockRpcClient.getGroupsBatch).not.toHaveBeenCalled()
        })
    })

    describe('fetchGroupTypesByTeamIds', () => {
        it('converts proto mappings to domain format keyed by team ID', async () => {
            mockRpcClient.getGroupTypeMappingsByTeamIds.mockResolvedValue({
                results: [
                    {
                        key: BigInt(1),
                        mappings: [
                            { groupType: 'organization', groupTypeIndex: 0 },
                            { groupType: 'project', groupTypeIndex: 1 },
                        ],
                    },
                    {
                        key: BigInt(2),
                        mappings: [{ groupType: 'company', groupTypeIndex: 0 }],
                    },
                ],
            })

            const result = await client.fetchGroupTypesByTeamIds([1, 2])

            expect(result).toEqual({
                '1': [
                    { group_type: 'organization', group_type_index: 0 },
                    { group_type: 'project', group_type_index: 1 },
                ],
                '2': [{ group_type: 'company', group_type_index: 0 }],
            })
        })

        it('returns empty object for empty input without calling gRPC', async () => {
            const result = await client.fetchGroupTypesByTeamIds([])

            expect(result).toEqual({})
            expect(mockRpcClient.getGroupTypeMappingsByTeamIds).not.toHaveBeenCalled()
        })
    })

    describe('fetchGroupTypesByProjectIds', () => {
        it('converts proto mappings to domain format keyed by project ID', async () => {
            mockRpcClient.getGroupTypeMappingsByProjectIds.mockResolvedValue({
                results: [
                    {
                        key: BigInt(100),
                        mappings: [{ groupType: 'workspace', groupTypeIndex: 0 }],
                    },
                ],
            })

            const result = await client.fetchGroupTypesByProjectIds([100])

            expect(result).toEqual({
                '100': [{ group_type: 'workspace', group_type_index: 0 }],
            })
        })

        it('returns empty object for empty input without calling gRPC', async () => {
            const result = await client.fetchGroupTypesByProjectIds([])

            expect(result).toEqual({})
            expect(mockRpcClient.getGroupTypeMappingsByProjectIds).not.toHaveBeenCalled()
        })
    })

    // -----------------------------------------------------------------------
    // Schema fidelity: use real protobuf Message instances via create()
    // to verify our conversion code handles actual proto objects, not just
    // plain JS objects with matching field names.
    // -----------------------------------------------------------------------
    describe('schema fidelity with real protobuf messages', () => {
        it('fetchGroup converts a real protobuf Group message', async () => {
            const protoGroup = makeRealProtoGroup()
            mockRpcClient.getGroup.mockResolvedValue(create(GetGroupResponseSchema, { group: protoGroup }))

            const result = await client.fetchGroup(1, 0, 'acme-corp')

            expect(result).toEqual({
                id: 42,
                team_id: 1,
                group_type_index: 0,
                group_key: 'acme-corp',
                group_properties: { name: 'Acme Corp', industry: 'tech' },
                properties_last_updated_at: { name: '2024-06-15T12:00:00Z' },
                properties_last_operation: { name: 'set' },
                created_at: DateTime.fromISO('2024-06-15T12:00:00.000Z', { zone: 'utc' }),
                version: 3,
            })
        })

        it('fetchGroupsByKeys converts real protobuf GroupWithKey messages', async () => {
            const response = create(GetGroupsBatchResponseSchema, {
                results: [
                    create(GroupWithKeySchema, {
                        key: create(GroupKeySchema, {
                            teamId: BigInt(1),
                            groupTypeIndex: 0,
                            groupKey: 'acme',
                        }),
                        group: makeRealProtoGroup({ groupProperties: jsonBytes({ name: 'Acme' }) }),
                    }),
                ],
            })
            mockRpcClient.getGroupsBatch.mockResolvedValue(response)

            const result = await client.fetchGroupsByKeys([1], [0], ['acme'])

            expect(result).toEqual([
                { team_id: 1, group_type_index: 0, group_key: 'acme', group_properties: { name: 'Acme' } },
            ])
        })

        it('fetchGroupTypesByTeamIds converts real protobuf mapping messages', async () => {
            const response = create(GroupTypeMappingsBatchResponseSchema, {
                results: [
                    create(GroupTypeMappingsByKeySchema, {
                        key: BigInt(5),
                        mappings: [
                            create(GroupTypeMappingSchema, { groupType: 'organization', groupTypeIndex: 0 }),
                            create(GroupTypeMappingSchema, { groupType: 'project', groupTypeIndex: 1 }),
                        ],
                    }),
                ],
            })
            mockRpcClient.getGroupTypeMappingsByTeamIds.mockResolvedValue(response)

            const result = await client.fetchGroupTypesByTeamIds([5])

            expect(result).toEqual({
                '5': [
                    { group_type: 'organization', group_type_index: 0 },
                    { group_type: 'project', group_type_index: 1 },
                ],
            })
        })

        it('fetchGroupTypesByProjectIds converts real protobuf mapping messages', async () => {
            const response = create(GroupTypeMappingsBatchResponseSchema, {
                results: [
                    create(GroupTypeMappingsByKeySchema, {
                        key: BigInt(200),
                        mappings: [create(GroupTypeMappingSchema, { groupType: 'team', groupTypeIndex: 2 })],
                    }),
                ],
            })
            mockRpcClient.getGroupTypeMappingsByProjectIds.mockResolvedValue(response)

            const result = await client.fetchGroupTypesByProjectIds([200])

            expect(result).toEqual({
                '200': [{ group_type: 'team', group_type_index: 2 }],
            })
        })
    })

    // -----------------------------------------------------------------------
    // Edge cases in data conversion
    // -----------------------------------------------------------------------
    describe('data conversion edge cases', () => {
        it('handles deeply nested JSON in group_properties', async () => {
            const nested = {
                org: {
                    settings: {
                        billing: { plan: 'enterprise', addons: ['sso', 'audit-log'] },
                        limits: { users: 500, projects: 100 },
                    },
                },
                tags: ['b2b', 'saas'],
                active: true,
                score: 99.5,
            }
            mockRpcClient.getGroup.mockResolvedValue({
                group: makePlainProtoGroup({ groupProperties: jsonBytes(nested) }),
            })

            const result = await client.fetchGroup(1, 0, 'nested')

            expect(result!.group_properties).toEqual(nested)
        })

        it('handles unicode and special characters in group keys and properties', async () => {
            const unicodeProps = {
                name: '日本語テスト',
                emoji: '🚀✨',
                quotes: 'he said "hello"',
                newlines: 'line1\nline2',
                backslash: 'path\\to\\thing',
            }
            mockRpcClient.getGroup.mockResolvedValue({
                group: makePlainProtoGroup({
                    groupKey: 'grp-日本語-🚀',
                    groupProperties: jsonBytes(unicodeProps),
                }),
            })

            const result = await client.fetchGroup(1, 0, 'grp-日本語-🚀')

            expect(result!.group_key).toBe('grp-日本語-🚀')
            expect(result!.group_properties).toEqual(unicodeProps)
        })

        it('handles large bigint IDs near Number.MAX_SAFE_INTEGER', async () => {
            const largeId = BigInt(Number.MAX_SAFE_INTEGER)
            mockRpcClient.getGroup.mockResolvedValue({
                group: makePlainProtoGroup({ id: largeId, version: largeId }),
            })

            const result = await client.fetchGroup(1, 0, 'big-ids')

            expect(result!.id).toBe(Number.MAX_SAFE_INTEGER)
            expect(result!.version).toBe(Number.MAX_SAFE_INTEGER)
        })

        it('handles group_properties containing null values', async () => {
            const propsWithNulls = { name: 'Acme', website: null, count: 0, active: false }
            mockRpcClient.getGroup.mockResolvedValue({
                group: makePlainProtoGroup({ groupProperties: jsonBytes(propsWithNulls) }),
            })

            const result = await client.fetchGroup(1, 0, 'nulls')

            expect(result!.group_properties).toEqual(propsWithNulls)
        })

        it('handles empty string group key', async () => {
            mockRpcClient.getGroup.mockResolvedValue({
                group: makePlainProtoGroup({ groupKey: '' }),
            })

            const result = await client.fetchGroup(1, 0, '')

            expect(result!.group_key).toBe('')
        })
    })

    // -----------------------------------------------------------------------
    // Request construction: verify the client sends correctly-formed protos
    // -----------------------------------------------------------------------
    describe('request construction', () => {
        it('fetchGroup sends correct request with BigInt teamId and eventual consistency', async () => {
            mockRpcClient.getGroup.mockResolvedValue({})

            await client.fetchGroup(42, 2, 'my-group')

            const request = mockRpcClient.getGroup.mock.calls[0][0]
            expect(request.teamId).toBe(BigInt(42))
            expect(request.groupTypeIndex).toBe(2)
            expect(request.groupKey).toBe('my-group')
            expect(request.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
        })

        it('fetchGroupsByKeys sends correct batch request with GroupKey protos', async () => {
            mockRpcClient.getGroupsBatch.mockResolvedValue({ results: [] })

            await client.fetchGroupsByKeys([10, 20], [0, 3], ['key-a', 'key-b'])

            const request = mockRpcClient.getGroupsBatch.mock.calls[0][0]
            expect(request.keys).toHaveLength(2)
            expect(request.keys[0].teamId).toBe(BigInt(10))
            expect(request.keys[0].groupTypeIndex).toBe(0)
            expect(request.keys[0].groupKey).toBe('key-a')
            expect(request.keys[1].teamId).toBe(BigInt(20))
            expect(request.keys[1].groupTypeIndex).toBe(3)
            expect(request.keys[1].groupKey).toBe('key-b')
            expect(request.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
        })

        it('fetchGroupTypesByTeamIds sends correct request with BigInt team IDs', async () => {
            mockRpcClient.getGroupTypeMappingsByTeamIds.mockResolvedValue({ results: [] })

            await client.fetchGroupTypesByTeamIds([1, 2, 3])

            const request = mockRpcClient.getGroupTypeMappingsByTeamIds.mock.calls[0][0]
            expect(request.teamIds).toEqual([BigInt(1), BigInt(2), BigInt(3)])
            expect(request.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
        })

        it('fetchGroupTypesByProjectIds sends correct request with BigInt project IDs', async () => {
            mockRpcClient.getGroupTypeMappingsByProjectIds.mockResolvedValue({ results: [] })

            await client.fetchGroupTypesByProjectIds([100, 200])

            const request = mockRpcClient.getGroupTypeMappingsByProjectIds.mock.calls[0][0]
            expect(request.projectIds).toEqual([BigInt(100), BigInt(200)])
            expect(request.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
        })
    })
})
