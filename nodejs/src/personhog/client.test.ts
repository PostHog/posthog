import { create } from '@bufbuild/protobuf'
import { Client } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogService } from '../generated/personhog/personhog/service/v1/service_pb'
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

type PersonHogRpcClient = Client<typeof PersonHogService>

const mockRpcClient: {
    [K in
        | 'getGroup'
        | 'getGroupsBatch'
        | 'getGroupTypeMappingsByTeamIds'
        | 'getGroupTypeMappingsByProjectIds']: jest.MockedFunction<PersonHogRpcClient[K]>
} = {
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

    function makeProtoGroup(
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

    function groupResponse(
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
        return create(GetGroupResponseSchema, { group: makeProtoGroup(overrides) })
    }

    function emptyGroupResponse() {
        return create(GetGroupResponseSchema, {})
    }

    describe('fetchGroup', () => {
        it('converts proto group to domain group', async () => {
            mockRpcClient.getGroup.mockResolvedValue(groupResponse())

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
            mockRpcClient.getGroup.mockResolvedValue(emptyGroupResponse())

            const result = await client.fetchGroup(1, 0, 'nonexistent')

            expect(result).toBeUndefined()
        })

        it('handles empty JSON bytes as empty objects', async () => {
            mockRpcClient.getGroup.mockResolvedValue(
                groupResponse({
                    groupProperties: new Uint8Array(0),
                    propertiesLastUpdatedAt: new Uint8Array(0),
                    propertiesLastOperation: new Uint8Array(0),
                })
            )

            const result = await client.fetchGroup(1, 0, 'empty-props')

            expect(result).toMatchObject({
                group_properties: {},
                properties_last_updated_at: {},
                properties_last_operation: {},
            })
        })

        it('converts bigint fields to numbers', async () => {
            mockRpcClient.getGroup.mockResolvedValue(
                groupResponse({
                    id: BigInt(999),
                    teamId: BigInt(77),
                    version: BigInt(15),
                })
            )

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
            const response = create(GetGroupsBatchResponseSchema, {
                results: [
                    create(GroupWithKeySchema, {
                        key: create(GroupKeySchema, { teamId: BigInt(1), groupTypeIndex: 0, groupKey: 'acme' }),
                        group: makeProtoGroup({ groupProperties: jsonBytes({ name: 'Acme' }) }),
                    }),
                    create(GroupWithKeySchema, {
                        key: create(GroupKeySchema, { teamId: BigInt(2), groupTypeIndex: 1, groupKey: 'globex' }),
                        group: makeProtoGroup({ groupProperties: jsonBytes({ name: 'Globex' }) }),
                    }),
                ],
            })
            mockRpcClient.getGroupsBatch.mockResolvedValue(response)

            const result = await client.fetchGroupsByKeys([1, 2], [0, 1], ['acme', 'globex'])

            expect(result).toEqual([
                { team_id: 1, group_type_index: 0, group_key: 'acme', group_properties: { name: 'Acme' } },
                { team_id: 2, group_type_index: 1, group_key: 'globex', group_properties: { name: 'Globex' } },
            ])
        })

        it('returns results in server response order regardless of request order', async () => {
            const response = create(GetGroupsBatchResponseSchema, {
                results: [
                    create(GroupWithKeySchema, {
                        key: create(GroupKeySchema, { teamId: BigInt(2), groupTypeIndex: 1, groupKey: 'globex' }),
                        group: makeProtoGroup({ groupProperties: jsonBytes({ name: 'Globex' }) }),
                    }),
                    create(GroupWithKeySchema, {
                        key: create(GroupKeySchema, { teamId: BigInt(1), groupTypeIndex: 0, groupKey: 'acme' }),
                        group: makeProtoGroup({ groupProperties: jsonBytes({ name: 'Acme' }) }),
                    }),
                ],
            })
            mockRpcClient.getGroupsBatch.mockResolvedValue(response)

            const result = await client.fetchGroupsByKeys([1, 2], [0, 1], ['acme', 'globex'])

            expect(result).toEqual([
                { team_id: 2, group_type_index: 1, group_key: 'globex', group_properties: { name: 'Globex' } },
                { team_id: 1, group_type_index: 0, group_key: 'acme', group_properties: { name: 'Acme' } },
            ])
        })

        it('skips results with missing group or key', async () => {
            const response = create(GetGroupsBatchResponseSchema, {
                results: [
                    create(GroupWithKeySchema, {
                        key: create(GroupKeySchema, { teamId: BigInt(1), groupTypeIndex: 0, groupKey: 'found' }),
                        group: makeProtoGroup(),
                    }),
                    create(GroupWithKeySchema, {
                        key: create(GroupKeySchema, { teamId: BigInt(1), groupTypeIndex: 0, groupKey: 'no-group' }),
                    }),
                    create(GroupWithKeySchema, {
                        group: makeProtoGroup(),
                    }),
                ],
            })
            mockRpcClient.getGroupsBatch.mockResolvedValue(response)

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
            const response = create(GroupTypeMappingsBatchResponseSchema, {
                results: [
                    create(GroupTypeMappingsByKeySchema, {
                        key: BigInt(1),
                        mappings: [
                            create(GroupTypeMappingSchema, { groupType: 'organization', groupTypeIndex: 0 }),
                            create(GroupTypeMappingSchema, { groupType: 'project', groupTypeIndex: 1 }),
                        ],
                    }),
                    create(GroupTypeMappingsByKeySchema, {
                        key: BigInt(2),
                        mappings: [create(GroupTypeMappingSchema, { groupType: 'company', groupTypeIndex: 0 })],
                    }),
                ],
            })
            mockRpcClient.getGroupTypeMappingsByTeamIds.mockResolvedValue(response)

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
            const response = create(GroupTypeMappingsBatchResponseSchema, {
                results: [
                    create(GroupTypeMappingsByKeySchema, {
                        key: BigInt(100),
                        mappings: [create(GroupTypeMappingSchema, { groupType: 'workspace', groupTypeIndex: 0 })],
                    }),
                ],
            })
            mockRpcClient.getGroupTypeMappingsByProjectIds.mockResolvedValue(response)

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
    // Empty result shape parity with Postgres
    // -----------------------------------------------------------------------
    // The Postgres GroupRepository pre-initializes empty arrays for ALL
    // requested IDs before populating results. The gRPC client only creates
    // entries for keys present in the response. This means a team/project
    // with no group types will have its key absent from the gRPC result
    // (whereas Postgres returns { "id": [] }). Downstream code handles
    // this via ?? [] fallbacks.
    describe('empty result shape parity with Postgres', () => {
        it('fetchGroupTypesByTeamIds omits key for team with no mappings', async () => {
            const response = create(GroupTypeMappingsBatchResponseSchema, {
                results: [
                    create(GroupTypeMappingsByKeySchema, {
                        key: BigInt(1),
                        mappings: [create(GroupTypeMappingSchema, { groupType: 'organization', groupTypeIndex: 0 })],
                    }),
                    // team 5 has no mappings — the server does not include it in results
                ],
            })
            mockRpcClient.getGroupTypeMappingsByTeamIds.mockResolvedValue(response)

            const result = await client.fetchGroupTypesByTeamIds([1, 5])

            // gRPC: key "5" is absent entirely
            expect(result).toEqual({
                '1': [{ group_type: 'organization', group_type_index: 0 }],
            })
            expect(result['5']).toBeUndefined()
            // Postgres would return: { "1": [...], "5": [] }
            // Downstream code uses result[teamId] ?? [] to handle the missing key
        })

        it('fetchGroupTypesByProjectIds omits key for project with no mappings', async () => {
            const response = create(GroupTypeMappingsBatchResponseSchema, {
                results: [
                    create(GroupTypeMappingsByKeySchema, {
                        key: BigInt(100),
                        mappings: [create(GroupTypeMappingSchema, { groupType: 'workspace', groupTypeIndex: 0 })],
                    }),
                    // project 200 has no mappings — not included in results
                ],
            })
            mockRpcClient.getGroupTypeMappingsByProjectIds.mockResolvedValue(response)

            const result = await client.fetchGroupTypesByProjectIds([100, 200])

            // gRPC: key "200" is absent entirely
            expect(result).toEqual({
                '100': [{ group_type: 'workspace', group_type_index: 0 }],
            })
            expect(result['200']).toBeUndefined()
            // Postgres would return: { "100": [...], "200": [] }
        })
    })

    // -----------------------------------------------------------------------
    // Schema fidelity: use real protobuf Message instances via create()
    // to verify our conversion code handles actual proto objects, not just
    // plain JS objects with matching field names.
    // -----------------------------------------------------------------------
    describe('schema fidelity with real protobuf messages', () => {
        it('fetchGroup converts a real protobuf Group message', async () => {
            mockRpcClient.getGroup.mockResolvedValue(groupResponse())

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
                        group: makeProtoGroup({ groupProperties: jsonBytes({ name: 'Acme' }) }),
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
            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ groupProperties: jsonBytes(nested) }))

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
            mockRpcClient.getGroup.mockResolvedValue(
                groupResponse({
                    groupKey: 'grp-日本語-🚀',
                    groupProperties: jsonBytes(unicodeProps),
                })
            )

            const result = await client.fetchGroup(1, 0, 'grp-日本語-🚀')

            expect(result!.group_key).toBe('grp-日本語-🚀')
            expect(result!.group_properties).toEqual(unicodeProps)
        })

        it('handles large bigint IDs near Number.MAX_SAFE_INTEGER', async () => {
            const largeId = BigInt(Number.MAX_SAFE_INTEGER)
            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ id: largeId, version: largeId }))

            const result = await client.fetchGroup(1, 0, 'big-ids')

            expect(result!.id).toBe(Number.MAX_SAFE_INTEGER)
            expect(result!.version).toBe(Number.MAX_SAFE_INTEGER)
        })

        it('handles group_properties containing null values', async () => {
            const propsWithNulls = { name: 'Acme', website: null, count: 0, active: false }
            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ groupProperties: jsonBytes(propsWithNulls) }))

            const result = await client.fetchGroup(1, 0, 'nulls')

            expect(result!.group_properties).toEqual(propsWithNulls)
        })

        it('handles empty string group key', async () => {
            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ groupKey: '' }))

            const result = await client.fetchGroup(1, 0, '')

            expect(result!.group_key).toBe('')
        })
    })

    // -----------------------------------------------------------------------
    // Timestamp conversion parity with Postgres
    // -----------------------------------------------------------------------
    // The Postgres path reads created_at as an ISO string and converts via
    // DateTime.fromISO(row.created_at).toUTC(). The gRPC path receives an
    // epoch-millisecond bigint and converts via DateTime.fromMillis(Number(epochMs), { zone: 'utc' }).
    // These tests document where the two paths agree and where they diverge.
    describe('timestamp conversion parity with Postgres', () => {
        function postgresPath(isoString: string): DateTime {
            return DateTime.fromISO(isoString).toUTC()
        }

        function grpcPath(epochMs: bigint): DateTime {
            return DateTime.fromMillis(Number(epochMs), { zone: 'utc' })
        }

        it('millisecond-precision timestamps produce identical DateTimes', async () => {
            const isoString = '2024-06-15T12:00:00.123Z'
            const epochMs = BigInt(DateTime.fromISO(isoString).toMillis())

            const fromPostgres = postgresPath(isoString)
            const fromGrpc = grpcPath(epochMs)

            expect(fromGrpc.toISO()).toBe(fromPostgres.toISO())
            expect(fromGrpc.toMillis()).toBe(fromPostgres.toMillis())

            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ createdAt: epochMs }))
            const result = await client.fetchGroup(1, 0, 'test')
            expect(result!.created_at.toISO()).toBe(fromPostgres.toISO())
        })

        it('microsecond-precision timestamps lose sub-millisecond precision in gRPC path', async () => {
            // Postgres stores microsecond precision: '2024-06-15T12:00:00.123456Z'
            // The ISO string preserves all 6 fractional digits.
            const isoString = '2024-06-15T12:00:00.123456Z'
            const fromPostgres = postgresPath(isoString)

            // Luxon's fromISO does NOT preserve microseconds — it truncates to milliseconds.
            // So Postgres path also loses microsecond precision at the Luxon boundary.
            expect(fromPostgres.toISO()).toBe('2024-06-15T12:00:00.123Z')

            // gRPC epoch_ms is inherently millisecond-precision, so .123456 becomes .123
            const epochMs = BigInt(1718452800123) // .123 seconds
            const fromGrpc = grpcPath(epochMs)

            // Both paths agree at millisecond precision because Luxon truncates
            // microseconds in fromISO as well. The precision loss is symmetric.
            expect(fromGrpc.toMillis()).toBe(fromPostgres.toMillis())
            expect(fromGrpc.toISO()).toBe('2024-06-15T12:00:00.123Z')

            // Document: if a future Luxon version or a different DateTime library
            // preserves microseconds, the gRPC path would diverge here.
            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ createdAt: epochMs }))
            const result = await client.fetchGroup(1, 0, 'test')
            expect(result!.created_at.toMillis()).toBe(fromPostgres.toMillis())
        })

        it('exact second boundary (no fractional seconds) produces identical DateTimes', async () => {
            const isoString = '2024-01-01T00:00:00.000Z'
            const epochMs = BigInt(DateTime.fromISO(isoString).toMillis())

            const fromPostgres = postgresPath(isoString)
            const fromGrpc = grpcPath(epochMs)

            expect(fromGrpc.toISO()).toBe(fromPostgres.toISO())
            expect(fromGrpc.toMillis()).toBe(fromPostgres.toMillis())
            expect(fromGrpc.toMillis()).toBe(1704067200000)

            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ createdAt: epochMs }))
            const result = await client.fetchGroup(1, 0, 'test')
            expect(result!.created_at.toISO()).toBe('2024-01-01T00:00:00.000Z')
        })

        it('epoch zero produces identical DateTimes', async () => {
            const isoString = '1970-01-01T00:00:00.000Z'
            const epochMs = BigInt(0)

            const fromPostgres = postgresPath(isoString)
            const fromGrpc = grpcPath(epochMs)

            expect(fromGrpc.toISO()).toBe(fromPostgres.toISO())
            expect(fromGrpc.toMillis()).toBe(0)
            expect(fromPostgres.toMillis()).toBe(0)

            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ createdAt: epochMs }))
            const result = await client.fetchGroup(1, 0, 'test')
            expect(result!.created_at.toMillis()).toBe(0)
            expect(result!.created_at.toISO()).toBe('1970-01-01T00:00:00.000Z')
        })
    })

    // -----------------------------------------------------------------------
    // JSONB encoding edge cases
    // -----------------------------------------------------------------------
    // The Postgres path applies sanitizeJsonbValue (strips \u0000 null bytes)
    // before storing. The gRPC path uses raw JSON.parse via parseJsonBytes.
    // These tests document behavior for edge-case property values.
    describe('JSONB encoding edge cases', () => {
        it('null bytes in property values are preserved by parseJsonBytes (unlike Postgres sanitization)', async () => {
            // Postgres sanitizeJsonbValue strips \u0000 before writing to JSONB.
            // If the personhog service serves data that was written through Postgres,
            // null bytes will already be stripped. But if data arrives without
            // sanitization, JSON.parse will preserve them.
            const propsWithNullByte = { name: 'test\u0000value', key: 'clean' }
            const bytes = jsonBytes(propsWithNullByte)

            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ groupProperties: bytes }))

            const result = await client.fetchGroup(1, 0, 'null-byte-test')

            // JSON.parse preserves the null byte — it does NOT strip \u0000
            expect(result!.group_properties.name).toBe('test\u0000value')
            expect(result!.group_properties.name).toHaveLength(10)
            // In contrast, Postgres-sanitized data would have: 'testvalue' (length 9)
        })

        it('very large string values in properties parse correctly', async () => {
            const largeValue = 'x'.repeat(1_000_000) // 1MB string
            const props = { big: largeValue }

            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ groupProperties: jsonBytes(props) }))

            const result = await client.fetchGroup(1, 0, 'large-props')

            expect(result!.group_properties.big).toHaveLength(1_000_000)
            expect(result!.group_properties.big).toBe(largeValue)
        })

        it('deeply nested objects with special characters parse correctly', async () => {
            const nested = {
                level1: {
                    level2: {
                        level3: {
                            level4: {
                                emoji: '🎉🔥',
                                quotes: '"hello\' world"',
                                tabs: 'col1\tcol2',
                                newlines: 'line1\nline2\rline3',
                                backslashes: 'C:\\Users\\test',
                                unicode: '\u00e9\u00e8\u00ea',
                            },
                        },
                    },
                },
            }

            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ groupProperties: jsonBytes(nested) }))

            const result = await client.fetchGroup(1, 0, 'deep-special')

            expect(result!.group_properties).toEqual(nested)
            expect(result!.group_properties.level1.level2.level3.level4.emoji).toBe('🎉🔥')
            expect(result!.group_properties.level1.level2.level3.level4.tabs).toContain('\t')
        })

        it.each([
            ['number', 42, 42],
            ['boolean true', true, true],
            ['boolean false', false, false],
            ['string', 'just a string', 'just a string'],
            ['array', [1, 'two', null, true], [1, 'two', null, true]],
            ['null', null, {}], // JSON.parse("null") returns null, then ?? {} fallback kicks in
        ])('top-level non-object value: %s', async (_label, rawValue, expected) => {
            // group_properties is typed as Record<string, any> but JSON.parse
            // can produce any valid JSON value. The ?? {} fallback in
            // protoGroupToDomain converts null to {}. For non-null non-object
            // values, the raw parsed value passes through.
            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ groupProperties: jsonBytes(rawValue) }))

            const result = await client.fetchGroup(1, 0, 'non-object-props')

            expect(result!.group_properties).toEqual(expected)
        })

        it('empty bytes produce empty object via fallback', async () => {
            mockRpcClient.getGroup.mockResolvedValue(
                groupResponse({
                    groupProperties: new Uint8Array(0),
                    propertiesLastUpdatedAt: new Uint8Array(0),
                    propertiesLastOperation: new Uint8Array(0),
                })
            )

            const result = await client.fetchGroup(1, 0, 'empty-bytes')

            expect(result!.group_properties).toEqual({})
            expect(result!.properties_last_updated_at).toEqual({})
            expect(result!.properties_last_operation).toEqual({})
        })

        it('empty object {} bytes produce empty object', async () => {
            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ groupProperties: jsonBytes({}) }))

            const result = await client.fetchGroup(1, 0, 'empty-obj')

            expect(result!.group_properties).toEqual({})
        })

        it('properties with mixed null-byte and clean values', async () => {
            const props = {
                clean: 'normal value',
                dirty: 'has\u0000null\u0000bytes',
                nested: { also_dirty: 'more\u0000nulls' },
            }

            mockRpcClient.getGroup.mockResolvedValue(groupResponse({ groupProperties: jsonBytes(props) }))

            const result = await client.fetchGroup(1, 0, 'mixed-nulls')

            // parseJsonBytes (JSON.parse) preserves all null bytes
            expect(result!.group_properties.clean).toBe('normal value')
            expect(result!.group_properties.dirty).toBe('has\u0000null\u0000bytes')
            expect(result!.group_properties.nested.also_dirty).toBe('more\u0000nulls')
        })
    })

    // -----------------------------------------------------------------------
    // Request construction: verify the client sends correctly-formed protos
    // -----------------------------------------------------------------------
    describe('request construction', () => {
        it('fetchGroup sends correct request with BigInt teamId and eventual consistency', async () => {
            mockRpcClient.getGroup.mockResolvedValue(emptyGroupResponse())

            await client.fetchGroup(42, 2, 'my-group')

            const request = mockRpcClient.getGroup.mock.calls[0][0]
            expect(request.teamId).toBe(BigInt(42))
            expect(request.groupTypeIndex).toBe(2)
            expect(request.groupKey).toBe('my-group')
            expect(request.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
        })

        it('fetchGroupsByKeys sends correct batch request with GroupKey protos', async () => {
            mockRpcClient.getGroupsBatch.mockResolvedValue(create(GetGroupsBatchResponseSchema, { results: [] }))

            await client.fetchGroupsByKeys([10, 20], [0, 3], ['key-a', 'key-b'])

            const request = mockRpcClient.getGroupsBatch.mock.calls[0][0]
            expect(request.keys).toHaveLength(2)
            expect(request.keys![0].teamId).toBe(BigInt(10))
            expect(request.keys![0].groupTypeIndex).toBe(0)
            expect(request.keys![0].groupKey).toBe('key-a')
            expect(request.keys![1].teamId).toBe(BigInt(20))
            expect(request.keys![1].groupTypeIndex).toBe(3)
            expect(request.keys![1].groupKey).toBe('key-b')
            expect(request.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
        })

        it('fetchGroupTypesByTeamIds sends correct request with BigInt team IDs', async () => {
            mockRpcClient.getGroupTypeMappingsByTeamIds.mockResolvedValue(
                create(GroupTypeMappingsBatchResponseSchema, { results: [] })
            )

            await client.fetchGroupTypesByTeamIds([1, 2, 3])

            const request = mockRpcClient.getGroupTypeMappingsByTeamIds.mock.calls[0][0]
            expect(request.teamIds).toEqual([BigInt(1), BigInt(2), BigInt(3)])
            expect(request.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
        })

        it('fetchGroupTypesByProjectIds sends correct request with BigInt project IDs', async () => {
            mockRpcClient.getGroupTypeMappingsByProjectIds.mockResolvedValue(
                create(GroupTypeMappingsBatchResponseSchema, { results: [] })
            )

            await client.fetchGroupTypesByProjectIds([100, 200])

            const request = mockRpcClient.getGroupTypeMappingsByProjectIds.mock.calls[0][0]
            expect(request.projectIds).toEqual([BigInt(100), BigInt(200)])
            expect(request.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
        })
    })
})
