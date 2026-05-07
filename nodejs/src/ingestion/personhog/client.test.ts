import { create } from '@bufbuild/protobuf'
import { Code, ConnectError, type ServiceImpl, createRouterTransport } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogService } from '../../generated/personhog/personhog/service/v1/service_pb'
import { ConsistencyLevel } from '../../generated/personhog/personhog/types/v1/common_pb'
import {
    GroupSchema,
    GroupTypeMappingSchema,
    GroupTypeMappingsByKeySchema,
} from '../../generated/personhog/personhog/types/v1/group_pb'
import type {
    GetGroupRequest,
    GetGroupTypeMappingsByProjectIdsRequest,
    GetGroupTypeMappingsByTeamIdsRequest,
    GetGroupsBatchRequest,
} from '../../generated/personhog/personhog/types/v1/group_pb'
import { PersonSchema } from '../../generated/personhog/personhog/types/v1/person_pb'
import type {
    GetPersonsByDistinctIdsRequest,
    GetPersonsByUuidsRequest,
} from '../../generated/personhog/personhog/types/v1/person_pb'
import {
    PersonHogClient,
    parseRolloutTeamIds,
    shouldUseGrpcForTeam,
    shouldUseGrpcForTeamItems,
    shouldUseGrpcForTeams,
} from './client'

const textEncoder = new TextEncoder()

function jsonBytes(obj: unknown): Uint8Array {
    return textEncoder.encode(JSON.stringify(obj))
}

const CREATED_AT_MS = BigInt(DateTime.fromISO('2024-06-15T12:00:00.000Z', { zone: 'utc' }).toMillis())

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
        id: 42n,
        teamId: 1n,
        groupTypeIndex: 0,
        groupKey: 'acme-corp',
        groupProperties: jsonBytes({ name: 'Acme Corp', industry: 'tech' }),
        createdAt: CREATED_AT_MS,
        propertiesLastUpdatedAt: jsonBytes({ name: '2024-06-15T12:00:00Z' }),
        propertiesLastOperation: jsonBytes({ name: 'set' }),
        version: 3n,
        ...overrides,
    })
}

function makeProtoPerson(
    overrides: Partial<{
        id: bigint
        uuid: string
        teamId: bigint
        properties: Uint8Array
        propertiesLastUpdatedAt: Uint8Array
        propertiesLastOperation: Uint8Array
        createdAt: bigint
        version: bigint
        isIdentified: boolean
        isUserId: boolean
        lastSeenAt: bigint
    }> = {}
) {
    return create(PersonSchema, {
        id: 42n,
        uuid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        teamId: 1n,
        properties: jsonBytes({ name: 'Test User', email: 'test@example.com' }),
        propertiesLastUpdatedAt: jsonBytes({ name: '2024-06-15T12:00:00Z' }),
        propertiesLastOperation: jsonBytes({ name: 'set' }),
        createdAt: CREATED_AT_MS,
        version: 3n,
        isIdentified: true,
        ...overrides,
    })
}

const SERVICE_DEFAULTS: ServiceImpl<typeof PersonHogService> = {
    getGroup: () => ({}),
    getGroups: () => ({ groups: [], missingGroups: [] }),
    getGroupsBatch: () => ({ results: [] }),
    getGroupTypeMappingsByTeamId: () => ({ mappings: [] }),
    getGroupTypeMappingsByTeamIds: () => ({ results: [] }),
    getGroupTypeMappingsByProjectId: () => ({ mappings: [] }),
    getGroupTypeMappingsByProjectIds: () => ({ results: [] }),
    getGroupTypeMappingByDashboardId: () => ({}),
    createGroup: () => ({}),
    updateGroup: () => ({ updated: false }),
    deleteGroupsBatchForTeam: () => ({ deletedCount: 0n }),
    updateGroupTypeMapping: () => ({}),
    deleteGroupTypeMapping: () => ({ deleted: false }),
    deleteGroupTypeMappingsBatchForTeam: () => ({ deletedCount: 0n }),
    getPerson: () => ({}),
    getPersons: () => ({ persons: [] }),
    getPersonByUuid: () => ({}),
    getPersonsByUuids: () => ({ persons: [] }),
    getPersonByDistinctId: () => ({}),
    getPersonsByDistinctIdsInTeam: () => ({ results: [] }),
    getPersonsByDistinctIds: () => ({ results: [] }),
    getDistinctIdsForPerson: () => ({ distinctIds: [] }),
    getDistinctIdsForPersons: () => ({ personDistinctIds: [] }),
    getHashKeyOverrideContext: () => ({ results: [] }),
    upsertHashKeyOverrides: () => ({}),
    deleteHashKeyOverridesByTeams: () => ({}),
    checkCohortMembership: () => ({ memberships: [] }),
    countCohortMembers: () => ({ count: 0n }),
    deleteCohortMember: () => ({ deleted: false }),
    deleteCohortMembersBulk: () => ({ deletedCount: 0n }),
    insertCohortMembers: () => ({ insertedCount: 0n }),
    listCohortMemberIds: () => ({ personIds: [], nextCursor: 0n }),
    updatePersonProperties: () => ({}),
    deletePersons: () => ({ deletedCount: 0n }),
    deletePersonsBatchForTeam: () => ({ deletedCount: 0n }),
}

function createMockClient(overrides: Partial<ServiceImpl<typeof PersonHogService>> = {}): PersonHogClient {
    const transport = createRouterTransport(({ service }) => {
        service(PersonHogService, {
            ...SERVICE_DEFAULTS,
            ...overrides,
        })
    })
    return PersonHogClient.fromTransport(transport)
}

describe('parseRolloutTeamIds', () => {
    it('returns empty set for empty string', () => {
        expect(parseRolloutTeamIds('')).toEqual(new Set())
    })

    it('returns empty set for whitespace-only string', () => {
        expect(parseRolloutTeamIds('   ')).toEqual(new Set())
    })

    it('parses comma-separated team IDs', () => {
        expect(parseRolloutTeamIds('1,2,3')).toEqual(new Set([1, 2, 3]))
    })

    it('handles whitespace around IDs', () => {
        expect(parseRolloutTeamIds(' 1 , 2 , 3 ')).toEqual(new Set([1, 2, 3]))
    })

    it('ignores non-numeric values', () => {
        expect(parseRolloutTeamIds('1,abc,3')).toEqual(new Set([1, 3]))
    })

    it('deduplicates IDs', () => {
        expect(parseRolloutTeamIds('1,1,2')).toEqual(new Set([1, 2]))
    })
})

describe('shouldUseGrpcForTeam', () => {
    it('returns true when team ID is in rollout set', () => {
        expect(shouldUseGrpcForTeam(new Set([1, 2, 3]), 2, 0)).toBe(true)
    })

    it('returns false when team ID is not in rollout set', () => {
        expect(shouldUseGrpcForTeam(new Set([1, 2, 3]), 99, 100)).toBe(false)
    })

    it('ignores percentage when rollout team IDs are set', () => {
        expect(shouldUseGrpcForTeam(new Set([1]), 99, 100)).toBe(false)
    })

    it('falls back to percentage when rollout set is empty', () => {
        // 100% should always return true
        expect(shouldUseGrpcForTeam(new Set(), 1, 100)).toBe(true)
    })

    it('falls back to percentage 0 when rollout set is empty', () => {
        expect(shouldUseGrpcForTeam(new Set(), 1, 0)).toBe(false)
    })
})

describe('shouldUseGrpcForTeams', () => {
    it('returns true when all team IDs are in rollout set', () => {
        expect(shouldUseGrpcForTeams(new Set([1, 5, 10]), [1, 5, 10], 0)).toBe(true)
    })

    it('returns false when only some team IDs are in rollout set', () => {
        expect(shouldUseGrpcForTeams(new Set([5]), [1, 5, 10], 100)).toBe(false)
    })

    it('returns false when no team IDs are in rollout set', () => {
        expect(shouldUseGrpcForTeams(new Set([99]), [1, 5, 10], 100)).toBe(false)
    })

    it('falls back to percentage when rollout set is empty', () => {
        expect(shouldUseGrpcForTeams(new Set(), [1], 100)).toBe(true)
    })

    it('returns false for empty team IDs array when rollout set is non-empty', () => {
        expect(shouldUseGrpcForTeams(new Set([1]), [], 100)).toBe(false)
    })
})

describe('shouldUseGrpcForTeamItems', () => {
    it('returns true when all items have team IDs in rollout set', () => {
        expect(shouldUseGrpcForTeamItems(new Set([1, 5]), [{ teamId: 1 }, { teamId: 5 }, { teamId: 1 }], 0)).toBe(true)
    })

    it('returns false when any item has a team ID not in rollout set', () => {
        expect(shouldUseGrpcForTeamItems(new Set([1]), [{ teamId: 1 }, { teamId: 99 }], 100)).toBe(false)
    })

    it('returns false for empty items when rollout set is non-empty', () => {
        expect(shouldUseGrpcForTeamItems(new Set([1]), [], 100)).toBe(false)
    })

    it('falls back to percentage when rollout set is empty', () => {
        expect(shouldUseGrpcForTeamItems(new Set(), [{ teamId: 1 }], 100)).toBe(true)
    })
})

describe('PersonHogClient', () => {
    describe('groups', () => {
        describe('fetchGroup', () => {
            it('converts proto group to domain group', async () => {
                const client = createMockClient({
                    getGroup: () => ({ group: makeProtoGroup() }),
                })

                const result = await client.groups.fetchGroup(1, 0, 'acme-corp')

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
                const client = createMockClient({
                    getGroup: () => ({}),
                })

                const result = await client.groups.fetchGroup(1, 0, 'nonexistent')

                expect(result).toBeUndefined()
            })

            it('handles empty JSON bytes as empty objects', async () => {
                const client = createMockClient({
                    getGroup: () => ({
                        group: makeProtoGroup({
                            groupProperties: new Uint8Array(0),
                            propertiesLastUpdatedAt: new Uint8Array(0),
                            propertiesLastOperation: new Uint8Array(0),
                        }),
                    }),
                })

                const result = await client.groups.fetchGroup(1, 0, 'empty-props')

                expect(result).toMatchObject({
                    group_properties: {},
                    properties_last_updated_at: {},
                    properties_last_operation: {},
                })
            })

            it('converts bigint fields to numbers', async () => {
                const client = createMockClient({
                    getGroup: () => ({
                        group: makeProtoGroup({ id: 999n, teamId: 77n, version: 15n }),
                    }),
                })

                const result = await client.groups.fetchGroup(77, 0, 'acme-corp')

                expect(result).toMatchObject({
                    id: 999,
                    team_id: 77,
                    version: 15,
                })
            })

            it('propagates gRPC errors', async () => {
                const client = createMockClient({
                    getGroup: () => {
                        throw new ConnectError('service unavailable', Code.Unavailable)
                    },
                })

                await expect(client.groups.fetchGroup(1, 0, 'key')).rejects.toThrow(ConnectError)
            })
        })

        describe('fetchGroupsByKeys', () => {
            it('converts batch proto response to domain objects', async () => {
                const client = createMockClient({
                    getGroupsBatch: () => ({
                        results: [
                            {
                                key: { teamId: 1n, groupTypeIndex: 0, groupKey: 'acme' },
                                group: makeProtoGroup({ groupProperties: jsonBytes({ name: 'Acme' }) }),
                            },
                            {
                                key: { teamId: 2n, groupTypeIndex: 1, groupKey: 'globex' },
                                group: makeProtoGroup({ groupProperties: jsonBytes({ name: 'Globex' }) }),
                            },
                        ],
                    }),
                })

                const result = await client.groups.fetchGroupsByKeys([1, 2], [0, 1], ['acme', 'globex'])

                expect(result).toEqual([
                    { team_id: 1, group_type_index: 0, group_key: 'acme', group_properties: { name: 'Acme' } },
                    { team_id: 2, group_type_index: 1, group_key: 'globex', group_properties: { name: 'Globex' } },
                ])
            })

            it('skips results with missing group (not found)', async () => {
                const client = createMockClient({
                    getGroupsBatch: () => ({
                        results: [
                            {
                                key: { teamId: 1n, groupTypeIndex: 0, groupKey: 'found' },
                                group: makeProtoGroup({ groupProperties: jsonBytes({ x: 1 }) }),
                            },
                            {
                                key: { teamId: 1n, groupTypeIndex: 1, groupKey: 'missing' },
                                // no group — server didn't find this one
                            },
                        ],
                    }),
                })

                const result = await client.groups.fetchGroupsByKeys([1, 1], [0, 1], ['found', 'missing'])

                expect(result).toEqual([
                    { team_id: 1, group_type_index: 0, group_key: 'found', group_properties: { x: 1 } },
                ])
            })

            it('returns empty array for empty input without calling gRPC', async () => {
                const handler = jest.fn()
                const client = createMockClient({ getGroupsBatch: handler })

                const result = await client.groups.fetchGroupsByKeys([], [], [])

                expect(result).toEqual([])
                expect(handler).not.toHaveBeenCalled()
            })
        })

        describe('fetchGroupTypesByTeamIds', () => {
            it('converts proto mappings to domain format keyed by team ID', async () => {
                const client = createMockClient({
                    getGroupTypeMappingsByTeamIds: () => ({
                        results: [
                            create(GroupTypeMappingsByKeySchema, {
                                key: 1n,
                                mappings: [
                                    create(GroupTypeMappingSchema, { groupType: 'organization', groupTypeIndex: 0 }),
                                    create(GroupTypeMappingSchema, { groupType: 'project', groupTypeIndex: 1 }),
                                ],
                            }),
                            create(GroupTypeMappingsByKeySchema, {
                                key: 2n,
                                mappings: [create(GroupTypeMappingSchema, { groupType: 'company', groupTypeIndex: 0 })],
                            }),
                        ],
                    }),
                })

                const result = await client.groups.fetchGroupTypesByTeamIds([1, 2])

                expect(result).toEqual({
                    '1': [
                        { group_type: 'organization', group_type_index: 0 },
                        { group_type: 'project', group_type_index: 1 },
                    ],
                    '2': [{ group_type: 'company', group_type_index: 0 }],
                })
            })

            it('returns empty object for empty input without calling gRPC', async () => {
                const handler = jest.fn()
                const client = createMockClient({ getGroupTypeMappingsByTeamIds: handler })

                const result = await client.groups.fetchGroupTypesByTeamIds([])

                expect(result).toEqual({})
                expect(handler).not.toHaveBeenCalled()
            })

            it('returns empty object when server returns no results', async () => {
                const client = createMockClient({
                    getGroupTypeMappingsByTeamIds: () => ({ results: [] }),
                })

                const result = await client.groups.fetchGroupTypesByTeamIds([999])

                expect(result).toEqual({})
            })
        })

        describe('fetchGroupTypesByProjectIds', () => {
            it('converts proto mappings to domain format keyed by project ID', async () => {
                const client = createMockClient({
                    getGroupTypeMappingsByProjectIds: () => ({
                        results: [
                            create(GroupTypeMappingsByKeySchema, {
                                key: 100n,
                                mappings: [
                                    create(GroupTypeMappingSchema, { groupType: 'workspace', groupTypeIndex: 0 }),
                                ],
                            }),
                        ],
                    }),
                })

                const result = await client.groups.fetchGroupTypesByProjectIds([100])

                expect(result).toEqual({
                    '100': [{ group_type: 'workspace', group_type_index: 0 }],
                })
            })

            it('returns empty object for empty input without calling gRPC', async () => {
                const handler = jest.fn()
                const client = createMockClient({ getGroupTypeMappingsByProjectIds: handler })

                const result = await client.groups.fetchGroupTypesByProjectIds([])

                expect(result).toEqual({})
                expect(handler).not.toHaveBeenCalled()
            })
        })

        describe('empty result shape parity with Postgres', () => {
            it('fetchGroupTypesByTeamIds omits key for team with no mappings', async () => {
                const client = createMockClient({
                    getGroupTypeMappingsByTeamIds: () => ({
                        results: [
                            create(GroupTypeMappingsByKeySchema, {
                                key: 1n,
                                mappings: [
                                    create(GroupTypeMappingSchema, { groupType: 'organization', groupTypeIndex: 0 }),
                                ],
                            }),
                            // team 5 has no mappings — server does not include it
                        ],
                    }),
                })

                const result = await client.groups.fetchGroupTypesByTeamIds([1, 5])

                expect(result).toEqual({
                    '1': [{ group_type: 'organization', group_type_index: 0 }],
                })
                expect(result['5']).toBeUndefined()
                // Postgres would return { "1": [...], "5": [] }
                // Downstream code uses result[teamId] ?? [] to handle this
            })

            it('fetchGroupTypesByProjectIds omits key for project with no mappings', async () => {
                const client = createMockClient({
                    getGroupTypeMappingsByProjectIds: () => ({
                        results: [
                            create(GroupTypeMappingsByKeySchema, {
                                key: 100n,
                                mappings: [
                                    create(GroupTypeMappingSchema, { groupType: 'workspace', groupTypeIndex: 0 }),
                                ],
                            }),
                            // project 200 has no mappings — not included
                        ],
                    }),
                })

                const result = await client.groups.fetchGroupTypesByProjectIds([100, 200])

                expect(result).toEqual({
                    '100': [{ group_type: 'workspace', group_type_index: 0 }],
                })
                expect(result['200']).toBeUndefined()
            })
        })

        describe('request construction', () => {
            it('fetchGroup sends correct request with BigInt teamId and eventual consistency', async () => {
                let capturedRequest: GetGroupRequest | undefined
                const client = createMockClient({
                    getGroup: (req) => {
                        capturedRequest = req
                        return {}
                    },
                })

                await client.groups.fetchGroup(42, 2, 'my-group')

                expect(capturedRequest!.teamId).toBe(42n)
                expect(capturedRequest!.groupTypeIndex).toBe(2)
                expect(capturedRequest!.groupKey).toBe('my-group')
                expect(capturedRequest!.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
            })

            it('fetchGroupsByKeys sends correct batch request with GroupKey protos', async () => {
                let capturedRequest: GetGroupsBatchRequest | undefined
                const client = createMockClient({
                    getGroupsBatch: (req) => {
                        capturedRequest = req
                        return { results: [] }
                    },
                })

                await client.groups.fetchGroupsByKeys([10, 20], [0, 3], ['key-a', 'key-b'])

                expect(capturedRequest!.keys).toHaveLength(2)
                expect(capturedRequest!.keys[0].teamId).toBe(10n)
                expect(capturedRequest!.keys[0].groupTypeIndex).toBe(0)
                expect(capturedRequest!.keys[0].groupKey).toBe('key-a')
                expect(capturedRequest!.keys[1].teamId).toBe(20n)
                expect(capturedRequest!.keys[1].groupTypeIndex).toBe(3)
                expect(capturedRequest!.keys[1].groupKey).toBe('key-b')
                expect(capturedRequest!.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
            })

            it('fetchGroupTypesByTeamIds sends correct request with BigInt team IDs', async () => {
                let capturedRequest: GetGroupTypeMappingsByTeamIdsRequest | undefined
                const client = createMockClient({
                    getGroupTypeMappingsByTeamIds: (req) => {
                        capturedRequest = req
                        return { results: [] }
                    },
                })

                await client.groups.fetchGroupTypesByTeamIds([1, 2, 3])

                expect(capturedRequest!.teamIds).toEqual([1n, 2n, 3n])
                expect(capturedRequest!.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
            })

            it('fetchGroupTypesByProjectIds sends correct request with BigInt project IDs', async () => {
                let capturedRequest: GetGroupTypeMappingsByProjectIdsRequest | undefined
                const client = createMockClient({
                    getGroupTypeMappingsByProjectIds: (req) => {
                        capturedRequest = req
                        return { results: [] }
                    },
                })

                await client.groups.fetchGroupTypesByProjectIds([100, 200])

                expect(capturedRequest!.projectIds).toEqual([100n, 200n])
                expect(capturedRequest!.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
            })
        })

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
                const client = createMockClient({
                    getGroup: () => ({ group: makeProtoGroup({ groupProperties: jsonBytes(nested) }) }),
                })

                const result = await client.groups.fetchGroup(1, 0, 'nested')

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
                const client = createMockClient({
                    getGroup: () => ({
                        group: makeProtoGroup({
                            groupKey: 'grp-日本語-🚀',
                            groupProperties: jsonBytes(unicodeProps),
                        }),
                    }),
                })

                const result = await client.groups.fetchGroup(1, 0, 'grp-日本語-🚀')

                expect(result!.group_key).toBe('grp-日本語-🚀')
                expect(result!.group_properties).toEqual(unicodeProps)
            })

            it('handles large bigint IDs near Number.MAX_SAFE_INTEGER', async () => {
                const largeId = BigInt(Number.MAX_SAFE_INTEGER)
                const client = createMockClient({
                    getGroup: () => ({ group: makeProtoGroup({ id: largeId, version: largeId }) }),
                })

                const result = await client.groups.fetchGroup(1, 0, 'big-ids')

                expect(result!.id).toBe(Number.MAX_SAFE_INTEGER)
                expect(result!.version).toBe(Number.MAX_SAFE_INTEGER)
            })

            it('handles group_properties containing null values', async () => {
                const propsWithNulls = { name: 'Acme', website: null, count: 0, active: false }
                const client = createMockClient({
                    getGroup: () => ({ group: makeProtoGroup({ groupProperties: jsonBytes(propsWithNulls) }) }),
                })

                const result = await client.groups.fetchGroup(1, 0, 'nulls')

                expect(result!.group_properties).toEqual(propsWithNulls)
            })

            it('handles empty string group key', async () => {
                const client = createMockClient({
                    getGroup: () => ({ group: makeProtoGroup({ groupKey: '' }) }),
                })

                const result = await client.groups.fetchGroup(1, 0, '')

                expect(result!.group_key).toBe('')
            })
        })

        describe('timestamp conversion parity with Postgres', () => {
            function postgresPath(isoString: string): DateTime {
                return DateTime.fromISO(isoString).toUTC()
            }

            it('millisecond-precision timestamps produce identical DateTimes', async () => {
                const isoString = '2024-06-15T12:00:00.123Z'
                const epochMs = BigInt(DateTime.fromISO(isoString).toMillis())
                const fromPostgres = postgresPath(isoString)

                const client = createMockClient({
                    getGroup: () => ({ group: makeProtoGroup({ createdAt: epochMs }) }),
                })
                const result = await client.groups.fetchGroup(1, 0, 'test')

                expect(result!.created_at.toISO()).toBe(fromPostgres.toISO())
                expect(result!.created_at.toMillis()).toBe(fromPostgres.toMillis())
            })

            it('exact second boundary produces identical DateTimes', async () => {
                const isoString = '2024-01-01T00:00:00.000Z'
                const epochMs = BigInt(DateTime.fromISO(isoString).toMillis())

                const client = createMockClient({
                    getGroup: () => ({ group: makeProtoGroup({ createdAt: epochMs }) }),
                })
                const result = await client.groups.fetchGroup(1, 0, 'test')

                expect(result!.created_at.toISO()).toBe(isoString)
                expect(result!.created_at.toMillis()).toBe(1704067200000)
            })

            it('epoch zero produces valid DateTime', async () => {
                const client = createMockClient({
                    getGroup: () => ({ group: makeProtoGroup({ createdAt: 0n }) }),
                })
                const result = await client.groups.fetchGroup(1, 0, 'test')

                expect(result!.created_at.toMillis()).toBe(0)
                expect(result!.created_at.toISO()).toBe('1970-01-01T00:00:00.000Z')
            })
        })
    })

    describe('persons', () => {
        describe('fetchPersonsByDistinctIds', () => {
            it('converts proto person to domain person with distinct_id', async () => {
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'user-123' },
                                person: makeProtoPerson(),
                            },
                        ],
                    }),
                })

                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'user-123' }])

                expect(result).toEqual([
                    {
                        id: '42',
                        uuid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                        team_id: 1,
                        properties: { name: 'Test User', email: 'test@example.com' },
                        properties_last_updated_at: { name: '2024-06-15T12:00:00Z' },
                        properties_last_operation: { name: 'set' },
                        created_at: DateTime.fromISO('2024-06-15T12:00:00.000Z', { zone: 'utc' }),
                        version: 3,
                        is_identified: true,
                        is_user_id: null,
                        last_seen_at: null,
                        distinct_id: 'user-123',
                    },
                ])
            })

            it('skips results with missing person (not found)', async () => {
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'found' },
                                person: makeProtoPerson(),
                            },
                            {
                                key: { teamId: 1n, distinctId: 'missing' },
                                // no person
                            },
                        ],
                    }),
                })

                const result = await client.persons.fetchPersonsByDistinctIds([
                    { teamId: 1, distinctId: 'found' },
                    { teamId: 1, distinctId: 'missing' },
                ])

                expect(result).toHaveLength(1)
                expect(result[0].distinct_id).toBe('found')
            })

            it('returns empty array for empty input without calling gRPC', async () => {
                const handler = jest.fn()
                const client = createMockClient({ getPersonsByDistinctIds: handler })

                const result = await client.persons.fetchPersonsByDistinctIds([])

                expect(result).toEqual([])
                expect(handler).not.toHaveBeenCalled()
            })

            it('handles empty JSON bytes as defaults', async () => {
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'user' },
                                person: makeProtoPerson({
                                    properties: new Uint8Array(0),
                                    propertiesLastUpdatedAt: new Uint8Array(0),
                                    propertiesLastOperation: new Uint8Array(0),
                                }),
                            },
                        ],
                    }),
                })

                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'user' }])

                expect(result[0].properties).toEqual({})
                expect(result[0].properties_last_updated_at).toEqual({})
                expect(result[0].properties_last_operation).toBeNull()
            })

            it('converts is_user_id correctly', async () => {
                const clientTrue = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'u' },
                                person: makeProtoPerson({ isUserId: true }),
                            },
                        ],
                    }),
                })
                const clientFalse = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'u' },
                                person: makeProtoPerson({ isUserId: false }),
                            },
                        ],
                    }),
                })

                const resultTrue = await clientTrue.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'u' }])
                const resultFalse = await clientFalse.persons.fetchPersonsByDistinctIds([
                    { teamId: 1, distinctId: 'u' },
                ])

                expect(resultTrue[0].is_user_id).toBe(1)
                expect(resultFalse[0].is_user_id).toBe(0)
            })

            it('converts last_seen_at when present', async () => {
                const lastSeenMs = BigInt(DateTime.fromISO('2024-12-25T10:30:00.000Z').toMillis())
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'u' },
                                person: makeProtoPerson({ lastSeenAt: lastSeenMs }),
                            },
                        ],
                    }),
                })

                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'u' }])

                expect(result[0].last_seen_at).toEqual(DateTime.fromISO('2024-12-25T10:30:00.000Z', { zone: 'utc' }))
            })

            it('propagates gRPC errors', async () => {
                const client = createMockClient({
                    getPersonsByDistinctIds: () => {
                        throw new ConnectError('service unavailable', Code.Unavailable)
                    },
                })

                await expect(
                    client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'u' }])
                ).rejects.toThrow(ConnectError)
            })

            it('sends correct request with BigInt teamId and eventual consistency', async () => {
                let capturedRequest: GetPersonsByDistinctIdsRequest | undefined
                const client = createMockClient({
                    getPersonsByDistinctIds: (req) => {
                        capturedRequest = req
                        return { results: [] }
                    },
                })

                await client.persons.fetchPersonsByDistinctIds([
                    { teamId: 42, distinctId: 'user-a' },
                    { teamId: 99, distinctId: 'user-b' },
                ])

                expect(capturedRequest!.teamDistinctIds).toHaveLength(2)
                expect(capturedRequest!.teamDistinctIds[0].teamId).toBe(42n)
                expect(capturedRequest!.teamDistinctIds[0].distinctId).toBe('user-a')
                expect(capturedRequest!.teamDistinctIds[1].teamId).toBe(99n)
                expect(capturedRequest!.teamDistinctIds[1].distinctId).toBe('user-b')
                expect(capturedRequest!.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
            })
        })

        describe('fetchPersonsByPersonIds', () => {
            it('converts proto persons to domain persons', async () => {
                const client = createMockClient({
                    getPersonsByUuids: () => ({
                        persons: [makeProtoPerson()],
                    }),
                })

                const result = await client.persons.fetchPersonsByPersonIds([
                    { teamId: 1, personId: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' },
                ])

                expect(result).toEqual([
                    {
                        id: '42',
                        uuid: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
                        team_id: 1,
                        properties: { name: 'Test User', email: 'test@example.com' },
                        properties_last_updated_at: { name: '2024-06-15T12:00:00Z' },
                        properties_last_operation: { name: 'set' },
                        created_at: DateTime.fromISO('2024-06-15T12:00:00.000Z', { zone: 'utc' }),
                        version: 3,
                        is_identified: true,
                        is_user_id: null,
                        last_seen_at: null,
                    },
                ])
            })

            it('returns empty array for empty input without calling gRPC', async () => {
                const handler = jest.fn()
                const client = createMockClient({ getPersonsByUuids: handler })

                const result = await client.persons.fetchPersonsByPersonIds([])

                expect(result).toEqual([])
                expect(handler).not.toHaveBeenCalled()
            })

            it('groups requests by team_id', async () => {
                const capturedRequests: GetPersonsByUuidsRequest[] = []
                const client = createMockClient({
                    getPersonsByUuids: (req) => {
                        capturedRequests.push(req)
                        return { persons: [] }
                    },
                })

                await client.persons.fetchPersonsByPersonIds([
                    { teamId: 1, personId: 'uuid-a' },
                    { teamId: 2, personId: 'uuid-b' },
                    { teamId: 1, personId: 'uuid-c' },
                ])

                expect(capturedRequests).toHaveLength(2)
                const team1Req = capturedRequests.find((r) => r.teamId === 1n)!
                const team2Req = capturedRequests.find((r) => r.teamId === 2n)!
                expect(team1Req.uuids).toEqual(['uuid-a', 'uuid-c'])
                expect(team2Req.uuids).toEqual(['uuid-b'])
            })

            it('sends correct request with BigInt teamId and eventual consistency', async () => {
                let capturedRequest: GetPersonsByUuidsRequest | undefined
                const client = createMockClient({
                    getPersonsByUuids: (req) => {
                        capturedRequest = req
                        return { persons: [] }
                    },
                })

                await client.persons.fetchPersonsByPersonIds([{ teamId: 42, personId: 'uuid-x' }])

                expect(capturedRequest!.teamId).toBe(42n)
                expect(capturedRequest!.uuids).toEqual(['uuid-x'])
                expect(capturedRequest!.readOptions?.consistency).toBe(ConsistencyLevel.EVENTUAL)
            })

            it('propagates gRPC errors', async () => {
                const client = createMockClient({
                    getPersonsByUuids: () => {
                        throw new ConnectError('timeout', Code.DeadlineExceeded)
                    },
                })

                await expect(
                    client.persons.fetchPersonsByPersonIds([{ teamId: 1, personId: 'uuid-a' }])
                ).rejects.toThrow(ConnectError)
            })
        })

        describe('data conversion edge cases', () => {
            it('handles deeply nested JSON in person properties', async () => {
                const nested = {
                    profile: {
                        settings: {
                            notifications: { email: true, push: false, sms: null },
                            theme: { mode: 'dark', colors: ['#000', '#fff'] },
                        },
                    },
                    tags: ['vip', 'beta'],
                    active: true,
                    score: 99.5,
                }
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'nested' },
                                person: makeProtoPerson({ properties: jsonBytes(nested) }),
                            },
                        ],
                    }),
                })

                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'nested' }])

                expect(result[0].properties).toEqual(nested)
            })

            it('handles unicode and special characters in properties', async () => {
                const unicodeProps = {
                    name: '日本語テスト',
                    emoji: '🚀✨',
                    quotes: 'he said "hello"',
                    newlines: 'line1\nline2',
                    backslash: 'path\\to\\thing',
                }
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'unicode' },
                                person: makeProtoPerson({ properties: jsonBytes(unicodeProps) }),
                            },
                        ],
                    }),
                })

                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'unicode' }])

                expect(result[0].properties).toEqual(unicodeProps)
            })

            it('handles large bigint IDs near Number.MAX_SAFE_INTEGER', async () => {
                const largeId = BigInt(Number.MAX_SAFE_INTEGER)
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'big' },
                                person: makeProtoPerson({ id: largeId, version: largeId }),
                            },
                        ],
                    }),
                })

                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'big' }])

                expect(result[0].id).toBe(String(Number.MAX_SAFE_INTEGER))
                expect(result[0].version).toBe(Number.MAX_SAFE_INTEGER)
            })

            it('handles properties containing null values', async () => {
                const propsWithNulls = { name: 'Alice', website: null, count: 0, active: false }
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'nulls' },
                                person: makeProtoPerson({ properties: jsonBytes(propsWithNulls) }),
                            },
                        ],
                    }),
                })

                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'nulls' }])

                expect(result[0].properties).toEqual(propsWithNulls)
            })

            it('person id is converted to string (not number)', async () => {
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'u' },
                                person: makeProtoPerson({ id: 999n }),
                            },
                        ],
                    }),
                })

                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'u' }])

                expect(result[0].id).toBe('999')
                expect(typeof result[0].id).toBe('string')
            })
        })

        describe('timestamp conversion', () => {
            function postgresPath(isoString: string): DateTime {
                return DateTime.fromISO(isoString).toUTC()
            }

            it('millisecond-precision created_at produces identical DateTime', async () => {
                const isoString = '2024-06-15T12:00:00.123Z'
                const epochMs = BigInt(DateTime.fromISO(isoString).toMillis())
                const fromPostgres = postgresPath(isoString)

                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'u' },
                                person: makeProtoPerson({ createdAt: epochMs }),
                            },
                        ],
                    }),
                })
                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'u' }])

                expect(result[0].created_at.toISO()).toBe(fromPostgres.toISO())
                expect(result[0].created_at.toMillis()).toBe(fromPostgres.toMillis())
            })

            it('epoch zero created_at produces valid DateTime', async () => {
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'u' },
                                person: makeProtoPerson({ createdAt: 0n }),
                            },
                        ],
                    }),
                })
                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'u' }])

                expect(result[0].created_at.toMillis()).toBe(0)
                expect(result[0].created_at.toISO()).toBe('1970-01-01T00:00:00.000Z')
            })

            it('millisecond-precision last_seen_at produces identical DateTime', async () => {
                const isoString = '2024-12-25T10:30:00.456Z'
                const epochMs = BigInt(DateTime.fromISO(isoString).toMillis())
                const fromPostgres = postgresPath(isoString)

                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'u' },
                                person: makeProtoPerson({ lastSeenAt: epochMs }),
                            },
                        ],
                    }),
                })
                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'u' }])

                expect(result[0].last_seen_at!.toISO()).toBe(fromPostgres.toISO())
                expect(result[0].last_seen_at!.toMillis()).toBe(fromPostgres.toMillis())
            })

            it('absent last_seen_at produces null', async () => {
                const client = createMockClient({
                    getPersonsByDistinctIds: () => ({
                        results: [
                            {
                                key: { teamId: 1n, distinctId: 'u' },
                                person: makeProtoPerson(),
                            },
                        ],
                    }),
                })
                const result = await client.persons.fetchPersonsByDistinctIds([{ teamId: 1, distinctId: 'u' }])

                expect(result[0].last_seen_at).toBeNull()
            })
        })
    })
})
