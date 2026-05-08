import { create } from '@bufbuild/protobuf'
import { Code, ConnectError, createRouterTransport } from '@connectrpc/connect'
import { DateTime } from 'luxon'

import { PersonHogService } from '../../generated/personhog/personhog/service/v1/service_pb'
import {
    GroupSchema,
    GroupTypeMappingSchema,
    GroupTypeMappingsByKeySchema,
} from '../../generated/personhog/personhog/types/v1/group_pb'
import { Group, GroupTypeIndex, ProjectId, TeamId } from '../../types'
import { GroupRepository } from '../../worker/ingestion/groups/repositories/group-repository.interface'
import { PersonHogClient } from './client'
import { PersonHogGroupRepository } from './personhog-group-repository'

jest.mock('../../utils/logger')

const textEncoder = new TextEncoder()

function jsonBytes(obj: unknown): Uint8Array {
    return textEncoder.encode(JSON.stringify(obj))
}

const TEAM_ID = 1 as TeamId
const GROUP_TYPE_INDEX = 0 as GroupTypeIndex
const GROUP_KEY = 'test-group'
const PROJECT_ID = 100 as ProjectId

const CREATED_AT = DateTime.fromISO('2024-01-01T00:00:00Z', { zone: 'utc' })

const TEST_GROUP: Group = {
    id: 42,
    team_id: TEAM_ID,
    group_type_index: GROUP_TYPE_INDEX,
    group_key: GROUP_KEY,
    group_properties: { name: 'Acme Corp', industry: 'tech' },
    properties_last_updated_at: {},
    properties_last_operation: {},
    created_at: CREATED_AT,
    version: 1,
}

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
        teamId: BigInt(TEAM_ID),
        groupTypeIndex: GROUP_TYPE_INDEX,
        groupKey: GROUP_KEY,
        groupProperties: jsonBytes({ name: 'Acme Corp', industry: 'tech' }),
        propertiesLastUpdatedAt: jsonBytes({}),
        propertiesLastOperation: jsonBytes({}),
        createdAt: BigInt(CREATED_AT.toMillis()),
        version: 1n,
        ...overrides,
    })
}

function makeGroupTypeMappingsProto(key: number | bigint, mappings: { groupType: string; groupTypeIndex: number }[]) {
    return create(GroupTypeMappingsByKeySchema, {
        key: BigInt(key),
        mappings: mappings.map((m) => create(GroupTypeMappingSchema, m)),
    })
}

const GROUP_TYPE_MAPPINGS = {
    [TEAM_ID.toString()]: [
        { group_type: 'organization', group_type_index: 0 as GroupTypeIndex },
        { group_type: 'project', group_type_index: 1 as GroupTypeIndex },
    ],
}

const GROUP_TYPE_MAPPINGS_PROTO = {
    results: [
        makeGroupTypeMappingsProto(TEAM_ID, [
            { groupType: 'organization', groupTypeIndex: 0 },
            { groupType: 'project', groupTypeIndex: 1 },
        ]),
    ],
}

function createMockPostgres(): jest.Mocked<GroupRepository> {
    return {
        fetchGroup: jest.fn(),
        fetchGroupsByKeys: jest.fn(),
        fetchGroupTypesByTeamIds: jest.fn(),
        fetchGroupTypesByProjectIds: jest.fn(),
        insertGroup: jest.fn(),
        updateGroup: jest.fn(),
        updateGroupOptimistically: jest.fn(),
        insertGroupType: jest.fn(),
        inTransaction: jest.fn(),
    }
}

type ServiceHandlers = {
    getGroup: jest.Mock
    getGroupsBatch: jest.Mock
    getGroupTypeMappingsByTeamIds: jest.Mock
    getGroupTypeMappingsByProjectIds: jest.Mock
}

function createGrpcClient(): { client: PersonHogClient; handlers: ServiceHandlers } {
    const handlers: ServiceHandlers = {
        getGroup: jest.fn(() => ({})),
        getGroupsBatch: jest.fn(() => ({ results: [] })),
        getGroupTypeMappingsByTeamIds: jest.fn(() => ({ results: [] })),
        getGroupTypeMappingsByProjectIds: jest.fn(() => ({ results: [] })),
    }

    const transport = createRouterTransport(({ service }) => {
        service(PersonHogService, {
            ...handlers,
            // no-op defaults for RPCs not under test
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
            countCohortMembers: () => ({ count: 0n }),
            deleteCohortMember: () => ({ deleted: false }),
            deleteCohortMembersBulk: () => ({ deletedCount: 0n }),
            insertCohortMembers: () => ({ insertedCount: 0n }),
            listCohortMemberIds: () => ({ personIds: [], nextCursor: 0n }),
            updatePersonProperties: () => ({}),
        })
    })

    return { client: PersonHogClient.fromTransport(transport), handlers }
}

describe('PersonHogGroupRepository', () => {
    let mockPostgres: jest.Mocked<GroupRepository>
    let grpcClient: PersonHogClient
    let handlers: ServiceHandlers

    beforeEach(() => {
        mockPostgres = createMockPostgres()
        const grpc = createGrpcClient()
        grpcClient = grpc.client
        handlers = grpc.handlers
    })

    function createRepo(grpcPercentage: number, rolloutTeamIds: Set<number> = new Set()): PersonHogGroupRepository {
        return new PersonHogGroupRepository(mockPostgres, grpcClient, grpcPercentage, rolloutTeamIds, 'test')
    }

    describe.each([
        ['postgres (rollout 0%)', 0],
        ['grpc (rollout 100%)', 100],
    ])('read path: %s', (_label, rolloutPercentage) => {
        const expectGrpc = rolloutPercentage === 100

        describe('fetchGroup', () => {
            it('returns the group for a replica read', async () => {
                mockPostgres.fetchGroup.mockResolvedValue(TEST_GROUP)
                handlers.getGroup.mockReturnValue({ group: makeProtoGroup() })

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, { useReadReplica: true })

                expect(result).toEqual(TEST_GROUP)
                if (expectGrpc) {
                    expect(handlers.getGroup).toHaveBeenCalled()
                    expect(mockPostgres.fetchGroup).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchGroup).toHaveBeenCalledWith(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, {
                        useReadReplica: true,
                    })
                    expect(handlers.getGroup).not.toHaveBeenCalled()
                }
            })

            it('returns undefined when the group does not exist', async () => {
                mockPostgres.fetchGroup.mockResolvedValue(undefined)
                handlers.getGroup.mockReturnValue({})

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, 'nonexistent', { useReadReplica: true })

                expect(result).toBeUndefined()
            })
        })

        describe('fetchGroupsByKeys', () => {
            const expectedResult = [
                {
                    team_id: TEAM_ID,
                    group_type_index: GROUP_TYPE_INDEX,
                    group_key: GROUP_KEY,
                    group_properties: { name: 'Acme Corp' },
                },
            ]

            it('returns matching groups', async () => {
                mockPostgres.fetchGroupsByKeys.mockResolvedValue(expectedResult)
                handlers.getGroupsBatch.mockReturnValue({
                    results: [
                        {
                            key: { teamId: BigInt(TEAM_ID), groupTypeIndex: GROUP_TYPE_INDEX, groupKey: GROUP_KEY },
                            group: makeProtoGroup({ groupProperties: jsonBytes({ name: 'Acme Corp' }) }),
                        },
                    ],
                })

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroupsByKeys([TEAM_ID], [GROUP_TYPE_INDEX], [GROUP_KEY])

                expect(result).toEqual(expectedResult)
                if (expectGrpc) {
                    expect(handlers.getGroupsBatch).toHaveBeenCalled()
                    expect(mockPostgres.fetchGroupsByKeys).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchGroupsByKeys).toHaveBeenCalledWith(
                        [TEAM_ID],
                        [GROUP_TYPE_INDEX],
                        [GROUP_KEY]
                    )
                    expect(handlers.getGroupsBatch).not.toHaveBeenCalled()
                }
            })

            it('returns empty array for empty input', async () => {
                mockPostgres.fetchGroupsByKeys.mockResolvedValue([])

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroupsByKeys([], [], [])

                expect(result).toEqual([])
            })
        })

        describe('fetchGroupTypesByTeamIds', () => {
            it('returns group type mappings', async () => {
                mockPostgres.fetchGroupTypesByTeamIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)
                handlers.getGroupTypeMappingsByTeamIds.mockReturnValue(GROUP_TYPE_MAPPINGS_PROTO)

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroupTypesByTeamIds([TEAM_ID])

                expect(result).toEqual(GROUP_TYPE_MAPPINGS)
                if (expectGrpc) {
                    expect(handlers.getGroupTypeMappingsByTeamIds).toHaveBeenCalled()
                    expect(mockPostgres.fetchGroupTypesByTeamIds).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([TEAM_ID])
                    expect(handlers.getGroupTypeMappingsByTeamIds).not.toHaveBeenCalled()
                }
            })
        })

        describe('fetchGroupTypesByProjectIds', () => {
            it('returns group type mappings', async () => {
                mockPostgres.fetchGroupTypesByProjectIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)
                handlers.getGroupTypeMappingsByProjectIds.mockReturnValue(GROUP_TYPE_MAPPINGS_PROTO)

                const repo = createRepo(rolloutPercentage)
                const result = await repo.fetchGroupTypesByProjectIds([PROJECT_ID])

                expect(result).toEqual(GROUP_TYPE_MAPPINGS)
                if (expectGrpc) {
                    expect(handlers.getGroupTypeMappingsByProjectIds).toHaveBeenCalled()
                    expect(mockPostgres.fetchGroupTypesByProjectIds).not.toHaveBeenCalled()
                } else {
                    expect(mockPostgres.fetchGroupTypesByProjectIds).toHaveBeenCalledWith([PROJECT_ID])
                    expect(handlers.getGroupTypeMappingsByProjectIds).not.toHaveBeenCalled()
                }
            })
        })
    })

    describe('fetchGroup always uses postgres when', () => {
        it.each([
            ['forUpdate is true', { forUpdate: true, useReadReplica: true }],
            ['useReadReplica is false', { forUpdate: false, useReadReplica: false }],
            ['useReadReplica is not set', { forUpdate: false }],
            ['no options provided', undefined],
        ])('%s', async (_label, options) => {
            mockPostgres.fetchGroup.mockResolvedValue(TEST_GROUP)
            const repo = createRepo(100)

            const result = await repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, options)

            expect(result).toEqual(TEST_GROUP)
            expect(mockPostgres.fetchGroup).toHaveBeenCalledWith(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, options)
            expect(handlers.getGroup).not.toHaveBeenCalled()
        })
    })

    describe('team ID-based rollout', () => {
        it('routes fetchGroup to gRPC when team ID is in rollout set (percentage 0)', async () => {
            handlers.getGroup.mockReturnValue({ group: makeProtoGroup() })

            const repo = createRepo(0, new Set([TEAM_ID]))
            const result = await repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, { useReadReplica: true })

            expect(result).toEqual(TEST_GROUP)
            expect(handlers.getGroup).toHaveBeenCalled()
            expect(mockPostgres.fetchGroup).not.toHaveBeenCalled()
        })

        it('routes fetchGroup to postgres when team ID is not in rollout set (percentage 0)', async () => {
            mockPostgres.fetchGroup.mockResolvedValue(TEST_GROUP)

            const repo = createRepo(0, new Set([999 as TeamId]))
            const result = await repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, { useReadReplica: true })

            expect(result).toEqual(TEST_GROUP)
            expect(mockPostgres.fetchGroup).toHaveBeenCalled()
            expect(handlers.getGroup).not.toHaveBeenCalled()
        })

        it('ignores percentage when team IDs are set', async () => {
            mockPostgres.fetchGroup.mockResolvedValue(TEST_GROUP)

            // percentage is 100 but team ID is not in the set — should use postgres
            const repo = createRepo(100, new Set([999 as TeamId]))
            const result = await repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, { useReadReplica: true })

            expect(result).toEqual(TEST_GROUP)
            expect(mockPostgres.fetchGroup).toHaveBeenCalled()
            expect(handlers.getGroup).not.toHaveBeenCalled()
        })

        it('routes fetchGroupsByKeys to gRPC when all team IDs are in rollout set', async () => {
            const expectedResult = [
                {
                    team_id: TEAM_ID,
                    group_type_index: GROUP_TYPE_INDEX,
                    group_key: GROUP_KEY,
                    group_properties: { name: 'Acme Corp' },
                },
            ]
            handlers.getGroupsBatch.mockReturnValue({
                results: [
                    {
                        key: { teamId: BigInt(TEAM_ID), groupTypeIndex: GROUP_TYPE_INDEX, groupKey: GROUP_KEY },
                        group: makeProtoGroup({ groupProperties: jsonBytes({ name: 'Acme Corp' }) }),
                    },
                ],
            })

            const repo = createRepo(0, new Set([TEAM_ID]))
            const result = await repo.fetchGroupsByKeys([TEAM_ID], [GROUP_TYPE_INDEX], [GROUP_KEY])

            expect(result).toEqual(expectedResult)
            expect(handlers.getGroupsBatch).toHaveBeenCalled()
            expect(mockPostgres.fetchGroupsByKeys).not.toHaveBeenCalled()
        })

        it('routes fetchGroupTypesByTeamIds to gRPC when all team IDs are in rollout set', async () => {
            handlers.getGroupTypeMappingsByTeamIds.mockReturnValue(GROUP_TYPE_MAPPINGS_PROTO)

            const repo = createRepo(0, new Set([TEAM_ID]))
            const result = await repo.fetchGroupTypesByTeamIds([TEAM_ID])

            expect(result).toEqual(GROUP_TYPE_MAPPINGS)
            expect(handlers.getGroupTypeMappingsByTeamIds).toHaveBeenCalled()
            expect(mockPostgres.fetchGroupTypesByTeamIds).not.toHaveBeenCalled()
        })

        it('routes fetchGroupTypesByTeamIds to postgres when not all team IDs are in rollout set', async () => {
            mockPostgres.fetchGroupTypesByTeamIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)

            const repo = createRepo(0, new Set([TEAM_ID]))
            const result = await repo.fetchGroupTypesByTeamIds([TEAM_ID, 999 as TeamId])

            expect(result).toEqual(GROUP_TYPE_MAPPINGS)
            expect(mockPostgres.fetchGroupTypesByTeamIds).toHaveBeenCalled()
            expect(handlers.getGroupTypeMappingsByTeamIds).not.toHaveBeenCalled()
        })
    })

    describe('grpc fallback to postgres on error', () => {
        it.each([
            [
                'fetchGroup',
                (h: ServiceHandlers, pg: jest.Mocked<GroupRepository>) => {
                    h.getGroup.mockImplementation(() => {
                        throw new ConnectError('connection refused', Code.Unavailable)
                    })
                    pg.fetchGroup.mockResolvedValue(TEST_GROUP)
                    return {
                        call: (repo: PersonHogGroupRepository) =>
                            repo.fetchGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, { useReadReplica: true }),
                        expected: TEST_GROUP,
                    }
                },
            ],
            [
                'fetchGroupsByKeys',
                (h: ServiceHandlers, pg: jest.Mocked<GroupRepository>) => {
                    const expected = [
                        {
                            team_id: TEAM_ID,
                            group_type_index: GROUP_TYPE_INDEX,
                            group_key: GROUP_KEY,
                            group_properties: {},
                        },
                    ]
                    h.getGroupsBatch.mockImplementation(() => {
                        throw new ConnectError('timeout', Code.DeadlineExceeded)
                    })
                    pg.fetchGroupsByKeys.mockResolvedValue(expected)
                    return {
                        call: (repo: PersonHogGroupRepository) =>
                            repo.fetchGroupsByKeys([TEAM_ID], [GROUP_TYPE_INDEX], [GROUP_KEY]),
                        expected,
                    }
                },
            ],
            [
                'fetchGroupTypesByTeamIds',
                (h: ServiceHandlers, pg: jest.Mocked<GroupRepository>) => {
                    h.getGroupTypeMappingsByTeamIds.mockImplementation(() => {
                        throw new ConnectError('unavailable', Code.Unavailable)
                    })
                    pg.fetchGroupTypesByTeamIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)
                    return {
                        call: (repo: PersonHogGroupRepository) => repo.fetchGroupTypesByTeamIds([TEAM_ID]),
                        expected: GROUP_TYPE_MAPPINGS,
                    }
                },
            ],
            [
                'fetchGroupTypesByProjectIds',
                (h: ServiceHandlers, pg: jest.Mocked<GroupRepository>) => {
                    h.getGroupTypeMappingsByProjectIds.mockImplementation(() => {
                        throw new ConnectError('unavailable', Code.Unavailable)
                    })
                    pg.fetchGroupTypesByProjectIds.mockResolvedValue(GROUP_TYPE_MAPPINGS)
                    return {
                        call: (repo: PersonHogGroupRepository) => repo.fetchGroupTypesByProjectIds([PROJECT_ID]),
                        expected: GROUP_TYPE_MAPPINGS,
                    }
                },
            ],
        ])(
            '%s falls back to postgres',
            async (
                _method,
                setup: (
                    h: ServiceHandlers,
                    pg: jest.Mocked<GroupRepository>
                ) => { call: (repo: PersonHogGroupRepository) => Promise<unknown>; expected: unknown }
            ) => {
                const { call, expected } = setup(handlers, mockPostgres)
                const repo = createRepo(100)

                const result = await call(repo)

                expect(result).toEqual(expected)
            }
        )
    })

    describe('gRPC empty result shape divergence from Postgres', () => {
        it('fetchGroupTypesByTeamIds with missing key works via ?? [] fallback', async () => {
            // gRPC returns {} when a team has no group types (key absent),
            // whereas Postgres returns { "5": [] } (key present with empty array).
            // Downstream code uses result[teamId] ?? [] so both shapes work.
            // The handler returns empty results, which PersonHogClient converts to {}.
            handlers.getGroupTypeMappingsByTeamIds.mockReturnValue({ results: [] })
            jest.spyOn(Math, 'random').mockReturnValue(0) // force gRPC path

            const repo = createRepo(100)
            const result = await repo.fetchGroupTypesByTeamIds([5 as TeamId])

            expect(result).toEqual({})
            // The caller would access result["5"] ?? [] and get []
            expect(result['5'] ?? []).toEqual([])

            jest.spyOn(Math, 'random').mockRestore()
        })

        it('fetchGroupTypesByProjectIds with missing key works via ?? [] fallback', async () => {
            handlers.getGroupTypeMappingsByProjectIds.mockReturnValue({ results: [] })
            jest.spyOn(Math, 'random').mockReturnValue(0) // force gRPC path

            const repo = createRepo(100)
            const result = await repo.fetchGroupTypesByProjectIds([200 as ProjectId])

            expect(result).toEqual({})
            expect(result['200'] ?? []).toEqual([])

            jest.spyOn(Math, 'random').mockRestore()
        })
    })

    describe('write operations always delegate to postgres', () => {
        it('insertGroup', async () => {
            mockPostgres.insertGroup.mockResolvedValue(1)
            const repo = createRepo(100)
            const now = DateTime.utc()

            const result = await repo.insertGroup(TEAM_ID, GROUP_TYPE_INDEX, GROUP_KEY, { name: 'test' }, now, {}, {})

            expect(result).toBe(1)
            expect(mockPostgres.insertGroup).toHaveBeenCalledWith(
                TEAM_ID,
                GROUP_TYPE_INDEX,
                GROUP_KEY,
                { name: 'test' },
                now,
                {},
                {}
            )
        })

        it('updateGroup', async () => {
            mockPostgres.updateGroup.mockResolvedValue(2)
            const repo = createRepo(100)
            const now = DateTime.utc()

            const result = await repo.updateGroup(
                TEAM_ID,
                GROUP_TYPE_INDEX,
                GROUP_KEY,
                { name: 'updated' },
                now,
                {},
                {},
                'test-tag'
            )

            expect(result).toBe(2)
            expect(mockPostgres.updateGroup).toHaveBeenCalledWith(
                TEAM_ID,
                GROUP_TYPE_INDEX,
                GROUP_KEY,
                { name: 'updated' },
                now,
                {},
                {},
                'test-tag'
            )
        })

        it('updateGroupOptimistically', async () => {
            mockPostgres.updateGroupOptimistically.mockResolvedValue(3)
            const repo = createRepo(100)
            const now = DateTime.utc()

            const result = await repo.updateGroupOptimistically(
                TEAM_ID,
                GROUP_TYPE_INDEX,
                GROUP_KEY,
                1,
                { name: 'opt' },
                now,
                {},
                {}
            )

            expect(result).toBe(3)
            expect(mockPostgres.updateGroupOptimistically).toHaveBeenCalledWith(
                TEAM_ID,
                GROUP_TYPE_INDEX,
                GROUP_KEY,
                1,
                { name: 'opt' },
                now,
                {},
                {}
            )
        })

        it('insertGroupType', async () => {
            mockPostgres.insertGroupType.mockResolvedValue([0 as GroupTypeIndex, true])
            const repo = createRepo(100)

            const result = await repo.insertGroupType(TEAM_ID, PROJECT_ID, 'organization', 0)

            expect(result).toEqual([0, true])
            expect(mockPostgres.insertGroupType).toHaveBeenCalledWith(TEAM_ID, PROJECT_ID, 'organization', 0)
        })

        it('inTransaction', async () => {
            mockPostgres.inTransaction.mockImplementation((_desc, fn) => fn({} as any))
            const repo = createRepo(100)

            await repo.inTransaction('test', () => Promise.resolve('done'))

            expect(mockPostgres.inTransaction).toHaveBeenCalled()
        })
    })
})
