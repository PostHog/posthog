import { create } from '@bufbuild/protobuf'
import { Code, ConnectError, createRouterTransport } from '@connectrpc/connect'
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
import { PersonHogClient } from './client'

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

// Handlers type: only the group RPCs we care about, all optional.
// Unspecified RPCs get safe no-op defaults.
type GroupHandlers = {
    getGroup?: (req: GetGroupRequest) => any
    getGroupsBatch?: (req: GetGroupsBatchRequest) => any
    getGroupTypeMappingsByTeamIds?: (req: GetGroupTypeMappingsByTeamIdsRequest) => any
    getGroupTypeMappingsByProjectIds?: (req: GetGroupTypeMappingsByProjectIdsRequest) => any
}

function createClientWithHandlers(handlers: GroupHandlers = {}): PersonHogClient {
    const transport = createRouterTransport(({ service }) => {
        service(PersonHogService, {
            getGroup: handlers.getGroup ?? (() => ({})),
            getGroupsBatch: handlers.getGroupsBatch ?? (() => ({ results: [] })),
            getGroupTypeMappingsByTeamIds: handlers.getGroupTypeMappingsByTeamIds ?? (() => ({ results: [] })),
            getGroupTypeMappingsByProjectIds: handlers.getGroupTypeMappingsByProjectIds ?? (() => ({ results: [] })),
            // no-op defaults for RPCs we don't test here
            getGroups: () => ({ groups: [], missingGroups: [] }),
            getGroupTypeMappingsByTeamId: () => ({ mappings: [] }),
            getGroupTypeMappingsByProjectId: () => ({ mappings: [] }),
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
            updatePersonProperties: () => ({}),
        })
    })
    return PersonHogClient.fromTransport(transport)
}

describe('PersonHogClient', () => {
    describe('fetchGroup', () => {
        it('converts proto group to domain group', async () => {
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
                getGroup: () => ({}),
            })

            const result = await client.groups.fetchGroup(1, 0, 'nonexistent')

            expect(result).toBeUndefined()
        })

        it('handles empty JSON bytes as empty objects', async () => {
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
                getGroup: () => {
                    throw new ConnectError('service unavailable', Code.Unavailable)
                },
            })

            await expect(client.groups.fetchGroup(1, 0, 'key')).rejects.toThrow(ConnectError)
        })
    })

    describe('fetchGroupsByKeys', () => {
        it('converts batch proto response to domain objects', async () => {
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({ getGroupsBatch: handler })

            const result = await client.groups.fetchGroupsByKeys([], [], [])

            expect(result).toEqual([])
            expect(handler).not.toHaveBeenCalled()
        })
    })

    describe('fetchGroupTypesByTeamIds', () => {
        it('converts proto mappings to domain format keyed by team ID', async () => {
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({ getGroupTypeMappingsByTeamIds: handler })

            const result = await client.groups.fetchGroupTypesByTeamIds([])

            expect(result).toEqual({})
            expect(handler).not.toHaveBeenCalled()
        })

        it('returns empty object when server returns no results', async () => {
            const client = createClientWithHandlers({
                getGroupTypeMappingsByTeamIds: () => ({ results: [] }),
            })

            const result = await client.groups.fetchGroupTypesByTeamIds([999])

            expect(result).toEqual({})
        })
    })

    describe('fetchGroupTypesByProjectIds', () => {
        it('converts proto mappings to domain format keyed by project ID', async () => {
            const client = createClientWithHandlers({
                getGroupTypeMappingsByProjectIds: () => ({
                    results: [
                        create(GroupTypeMappingsByKeySchema, {
                            key: 100n,
                            mappings: [create(GroupTypeMappingSchema, { groupType: 'workspace', groupTypeIndex: 0 })],
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
            const client = createClientWithHandlers({ getGroupTypeMappingsByProjectIds: handler })

            const result = await client.groups.fetchGroupTypesByProjectIds([])

            expect(result).toEqual({})
            expect(handler).not.toHaveBeenCalled()
        })
    })

    describe('empty result shape parity with Postgres', () => {
        it('fetchGroupTypesByTeamIds omits key for team with no mappings', async () => {
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
                getGroupTypeMappingsByProjectIds: () => ({
                    results: [
                        create(GroupTypeMappingsByKeySchema, {
                            key: 100n,
                            mappings: [create(GroupTypeMappingSchema, { groupType: 'workspace', groupTypeIndex: 0 })],
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
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
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
            const client = createClientWithHandlers({
                getGroup: () => ({ group: makeProtoGroup({ id: largeId, version: largeId }) }),
            })

            const result = await client.groups.fetchGroup(1, 0, 'big-ids')

            expect(result!.id).toBe(Number.MAX_SAFE_INTEGER)
            expect(result!.version).toBe(Number.MAX_SAFE_INTEGER)
        })

        it('handles group_properties containing null values', async () => {
            const propsWithNulls = { name: 'Acme', website: null, count: 0, active: false }
            const client = createClientWithHandlers({
                getGroup: () => ({ group: makeProtoGroup({ groupProperties: jsonBytes(propsWithNulls) }) }),
            })

            const result = await client.groups.fetchGroup(1, 0, 'nulls')

            expect(result!.group_properties).toEqual(propsWithNulls)
        })

        it('handles empty string group key', async () => {
            const client = createClientWithHandlers({
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

            const client = createClientWithHandlers({
                getGroup: () => ({ group: makeProtoGroup({ createdAt: epochMs }) }),
            })
            const result = await client.groups.fetchGroup(1, 0, 'test')

            expect(result!.created_at.toISO()).toBe(fromPostgres.toISO())
            expect(result!.created_at.toMillis()).toBe(fromPostgres.toMillis())
        })

        it('exact second boundary produces identical DateTimes', async () => {
            const isoString = '2024-01-01T00:00:00.000Z'
            const epochMs = BigInt(DateTime.fromISO(isoString).toMillis())

            const client = createClientWithHandlers({
                getGroup: () => ({ group: makeProtoGroup({ createdAt: epochMs }) }),
            })
            const result = await client.groups.fetchGroup(1, 0, 'test')

            expect(result!.created_at.toISO()).toBe(isoString)
            expect(result!.created_at.toMillis()).toBe(1704067200000)
        })

        it('epoch zero produces valid DateTime', async () => {
            const client = createClientWithHandlers({
                getGroup: () => ({ group: makeProtoGroup({ createdAt: 0n }) }),
            })
            const result = await client.groups.fetchGroup(1, 0, 'test')

            expect(result!.created_at.toMillis()).toBe(0)
            expect(result!.created_at.toISO()).toBe('1970-01-01T00:00:00.000Z')
        })
    })
})
