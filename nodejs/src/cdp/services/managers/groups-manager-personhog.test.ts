import { TeamManager } from '~/utils/team-manager'
import { GroupRepository } from '~/worker/ingestion/groups/repositories/group-repository.interface'

import { PersonHogClient } from '../../../ingestion/personhog/client'
import { PersonHogGroupRepository } from '../../../ingestion/personhog/personhog-group-repository'
import { GroupTypeIndex, TeamId } from '../../../types'
import { createHogExecutionGlobals } from '../../_tests/fixtures'
import { GroupsManagerService } from './groups-manager.service'

jest.mock('../../../utils/logger')

const TEAM_1 = 1 as TeamId
const TEAM_2 = 2 as TeamId

const MOCK_GROUP_TYPES = [
    { team_id: TEAM_1, group_type: 'GroupA', group_type_index: 0 as GroupTypeIndex },
    { team_id: TEAM_1, group_type: 'GroupB', group_type_index: 1 as GroupTypeIndex },
    { team_id: TEAM_2, group_type: 'GroupA', group_type_index: 1 as GroupTypeIndex },
]

const MOCK_GROUPS = [
    {
        team_id: TEAM_1,
        group_type_index: 0 as GroupTypeIndex,
        group_key: 'id-1',
        group_properties: { prop: 'value-1' },
    },
    {
        team_id: TEAM_1,
        group_type_index: 1 as GroupTypeIndex,
        group_key: 'id-2',
        group_properties: { prop: 'value-2' },
    },
    {
        team_id: TEAM_2,
        group_type_index: 1 as GroupTypeIndex,
        group_key: 'id-1',
        group_properties: { prop: 'value-team-2' },
    },
]

function createMockPostgres(
    groupTypes: typeof MOCK_GROUP_TYPES,
    groups: typeof MOCK_GROUPS
): jest.Mocked<GroupRepository> {
    const mock: jest.Mocked<GroupRepository> = {
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

    mock.fetchGroupTypesByTeamIds.mockImplementation((teamIds: TeamId[]) => {
        const result: Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]> = {}
        for (const teamId of teamIds) {
            result[teamId.toString()] = []
        }
        for (const gt of groupTypes) {
            if (teamIds.includes(gt.team_id)) {
                result[gt.team_id.toString()].push({
                    group_type: gt.group_type,
                    group_type_index: gt.group_type_index,
                })
            }
        }
        return Promise.resolve(result)
    })

    mock.fetchGroupsByKeys.mockImplementation(
        (teamIds: TeamId[], groupIndexes: GroupTypeIndex[], groupKeys: string[]) => {
            const results = groups.filter((group) => {
                for (let i = 0; i < teamIds.length; i++) {
                    if (
                        teamIds[i] === group.team_id &&
                        groupIndexes[i] === group.group_type_index &&
                        groupKeys[i] === group.group_key
                    ) {
                        return true
                    }
                }
                return false
            })
            return Promise.resolve(results)
        }
    )

    return mock
}

type MockPersonHogClient = {
    groups: jest.Mocked<
        Pick<
            PersonHogClient['groups'],
            'fetchGroup' | 'fetchGroupsByKeys' | 'fetchGroupTypesByTeamIds' | 'fetchGroupTypesByProjectIds'
        >
    >
}

function createMockGrpcClient(groupTypes: typeof MOCK_GROUP_TYPES, groups: typeof MOCK_GROUPS): MockPersonHogClient {
    const mock: MockPersonHogClient = {
        groups: {
            fetchGroup: jest.fn(),
            fetchGroupsByKeys: jest.fn(),
            fetchGroupTypesByTeamIds: jest.fn(),
            fetchGroupTypesByProjectIds: jest.fn(),
        },
    }

    mock.groups.fetchGroupTypesByTeamIds.mockImplementation((teamIds: number[]) => {
        const result: Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]> = {}
        for (const teamId of teamIds) {
            result[teamId.toString()] = []
        }
        for (const gt of groupTypes) {
            if (teamIds.includes(gt.team_id)) {
                result[gt.team_id.toString()].push({
                    group_type: gt.group_type,
                    group_type_index: gt.group_type_index,
                })
            }
        }
        return Promise.resolve(result)
    })

    mock.groups.fetchGroupsByKeys.mockImplementation(
        (teamIds: number[], groupIndexes: number[], groupKeys: string[]) => {
            const results = groups.filter((group) => {
                for (let i = 0; i < teamIds.length; i++) {
                    if (
                        teamIds[i] === group.team_id &&
                        groupIndexes[i] === group.group_type_index &&
                        groupKeys[i] === group.group_key
                    ) {
                        return true
                    }
                }
                return false
            })
            return Promise.resolve(results)
        }
    )

    return mock
}

describe('GroupsManagerService + PersonHogGroupRepository integration', () => {
    jest.setTimeout(1000)

    const mockHasAvailableFeature = jest.fn(() => Promise.resolve(true))
    const mockTeamManager = {
        hasAvailableFeature: mockHasAvailableFeature,
    } as unknown as TeamManager

    describe.each([
        ['postgres (rollout 0%)', 0],
        ['grpc (rollout 100%)', 100],
    ])('%s', (_label, rolloutPercentage) => {
        let mockPostgres: jest.Mocked<GroupRepository>
        let mockGrpc: ReturnType<typeof createMockGrpcClient>
        let groupsManager: GroupsManagerService

        beforeEach(() => {
            jest.restoreAllMocks()
            mockHasAvailableFeature.mockReturnValue(Promise.resolve(true))
            mockPostgres = createMockPostgres(MOCK_GROUP_TYPES, MOCK_GROUPS)
            mockGrpc = createMockGrpcClient(MOCK_GROUP_TYPES, MOCK_GROUPS)

            const personhogRepo = new PersonHogGroupRepository(
                mockPostgres,
                mockGrpc as unknown as PersonHogClient,
                rolloutPercentage,
                'test'
            )
            groupsManager = new GroupsManagerService(mockTeamManager, personhogRepo)
        })

        it('enriches simple groups', async () => {
            const globals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } },
                } as any,
            })

            await groupsManager.addGroupsToGlobals(globals)

            expect(globals.groups).toEqual({
                GroupA: {
                    id: 'id-1',
                    index: 0,
                    properties: { prop: 'value-1' },
                    type: 'GroupA',
                    url: 'http://localhost:8000/projects/1/groups/0/id-1',
                },
                GroupB: {
                    id: 'id-2',
                    index: 1,
                    properties: { prop: 'value-2' },
                    type: 'GroupB',
                    url: 'http://localhost:8000/projects/1/groups/1/id-2',
                },
            })

            if (rolloutPercentage === 100) {
                expect(mockGrpc.groups.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([TEAM_1])
                expect(mockGrpc.groups.fetchGroupsByKeys).toHaveBeenCalled()
                expect(mockPostgres.fetchGroupTypesByTeamIds).not.toHaveBeenCalled()
                expect(mockPostgres.fetchGroupsByKeys).not.toHaveBeenCalled()
            } else {
                expect(mockPostgres.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([TEAM_1])
                expect(mockPostgres.fetchGroupsByKeys).toHaveBeenCalled()
                expect(mockGrpc.groups.fetchGroupTypesByTeamIds).not.toHaveBeenCalled()
                expect(mockGrpc.groups.fetchGroupsByKeys).not.toHaveBeenCalled()
            }
        })

        it('enriches multiple globals from different teams concurrently', async () => {
            const items = [
                createHogExecutionGlobals({
                    groups: undefined,
                    event: { properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } } } as any,
                }),
                createHogExecutionGlobals({
                    groups: undefined,
                    project: { id: 2 } as any,
                    event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
                }),
            ]

            await Promise.all(items.map((item) => groupsManager.addGroupsToGlobals(item)))

            expect(items[0].groups).toEqual({
                GroupA: {
                    id: 'id-1',
                    index: 0,
                    properties: { prop: 'value-1' },
                    type: 'GroupA',
                    url: 'http://localhost:8000/projects/1/groups/0/id-1',
                },
                GroupB: {
                    id: 'id-2',
                    index: 1,
                    properties: { prop: 'value-2' },
                    type: 'GroupB',
                    url: 'http://localhost:8000/projects/1/groups/1/id-2',
                },
            })

            expect(items[1].groups).toEqual({
                GroupA: {
                    id: 'id-1',
                    index: 1,
                    properties: { prop: 'value-team-2' },
                    type: 'GroupA',
                    url: 'http://localhost:8000/projects/1/groups/1/id-1',
                },
            })
        })

        it('returns empty properties when group type exists but no matching group row', async () => {
            const globals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: { $groups: { GroupA: 'nonexistent-key' } },
                } as any,
            })

            await groupsManager.addGroupsToGlobals(globals)

            expect(globals.groups).toEqual({
                GroupA: {
                    id: 'nonexistent-key',
                    index: 0,
                    properties: {},
                    type: 'GroupA',
                    url: 'http://localhost:8000/projects/1/groups/0/nonexistent-key',
                },
            })
        })
    })

    describe('gRPC empty group type mapping key omission', () => {
        it('event with unknown group type is silently skipped when gRPC omits the mapping key', async () => {
            // The real PersonHogClient does NOT pre-initialize empty arrays for
            // requested team IDs that have no group type mappings — the key is
            // simply absent from the response. This differs from Postgres which
            // returns { "teamId": [] }. Verify that GroupsManagerService handles
            // the missing key via its ?? [] fallback and produces the correct result.
            const TEAM_3 = 3 as TeamId

            const mockPostgres = createMockPostgres([], [])
            const mockGrpc: MockPersonHogClient = {
                groups: {
                    fetchGroup: jest.fn(),
                    fetchGroupsByKeys: jest.fn().mockResolvedValue([]),
                    fetchGroupTypesByTeamIds: jest.fn().mockImplementation((_teamIds: number[]) => {
                        // Mimic real gRPC behavior: return empty object (no key for team 3)
                        return Promise.resolve({})
                    }),
                    fetchGroupTypesByProjectIds: jest.fn(),
                },
            }

            const personhogRepo = new PersonHogGroupRepository(
                mockPostgres,
                mockGrpc as unknown as PersonHogClient,
                100,
                'test'
            )
            const manager = new GroupsManagerService(
                { hasAvailableFeature: jest.fn().mockResolvedValue(true) } as unknown as TeamManager,
                personhogRepo
            )

            const globals = createHogExecutionGlobals({
                groups: undefined,
                project: { id: TEAM_3 } as any,
                event: {
                    properties: { $groups: { UnknownType: 'some-key' } },
                } as any,
            })

            await manager.addGroupsToGlobals(globals)

            // UnknownType has no mapping → skipped entirely → empty groups
            expect(globals.groups).toEqual({})
            expect(mockGrpc.groups.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([TEAM_3])
            // fetchGroupsByKeys should NOT be called since there are no valid group type mappings
            expect(mockGrpc.groups.fetchGroupsByKeys).not.toHaveBeenCalled()
        })
    })

    describe('grpc fallback to postgres on error', () => {
        let mockPostgres: jest.Mocked<GroupRepository>
        let mockGrpc: ReturnType<typeof createMockGrpcClient>
        let groupsManager: GroupsManagerService

        beforeEach(() => {
            jest.restoreAllMocks()
            mockHasAvailableFeature.mockReturnValue(Promise.resolve(true))
            mockPostgres = createMockPostgres(MOCK_GROUP_TYPES, MOCK_GROUPS)
            mockGrpc = createMockGrpcClient(MOCK_GROUP_TYPES, MOCK_GROUPS)

            const personhogRepo = new PersonHogGroupRepository(
                mockPostgres,
                mockGrpc as unknown as PersonHogClient,
                100,
                'test'
            )
            groupsManager = new GroupsManagerService(mockTeamManager, personhogRepo)
        })

        it('falls back to postgres when gRPC fetchGroupTypesByTeamIds fails', async () => {
            mockGrpc.groups.fetchGroupTypesByTeamIds.mockRejectedValue(new Error('connection refused'))

            const globals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: { $groups: { GroupA: 'id-1' } },
                } as any,
            })

            await groupsManager.addGroupsToGlobals(globals)

            expect(globals.groups).toEqual({
                GroupA: {
                    id: 'id-1',
                    index: 0,
                    properties: { prop: 'value-1' },
                    type: 'GroupA',
                    url: 'http://localhost:8000/projects/1/groups/0/id-1',
                },
            })

            // gRPC was called and failed
            expect(mockGrpc.groups.fetchGroupTypesByTeamIds).toHaveBeenCalled()
            // Postgres was called as fallback
            expect(mockPostgres.fetchGroupTypesByTeamIds).toHaveBeenCalled()
        })

        it('falls back to postgres when gRPC fetchGroupsByKeys fails', async () => {
            mockGrpc.groups.fetchGroupsByKeys.mockRejectedValue(new Error('timeout'))

            const globals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: { $groups: { GroupA: 'id-1' } },
                } as any,
            })

            await groupsManager.addGroupsToGlobals(globals)

            expect(globals.groups).toEqual({
                GroupA: {
                    id: 'id-1',
                    index: 0,
                    properties: { prop: 'value-1' },
                    type: 'GroupA',
                    url: 'http://localhost:8000/projects/1/groups/0/id-1',
                },
            })

            // gRPC fetchGroupsByKeys was called and failed
            expect(mockGrpc.groups.fetchGroupsByKeys).toHaveBeenCalled()
            // Postgres fetchGroupsByKeys was called as fallback
            expect(mockPostgres.fetchGroupsByKeys).toHaveBeenCalled()
        })

        it('produces identical output on fallback as on direct postgres path', async () => {
            // First: get the postgres-only result
            const postgresRepo = new PersonHogGroupRepository(
                mockPostgres,
                mockGrpc as unknown as PersonHogClient,
                0,
                'test'
            )
            const postgresManager = new GroupsManagerService(mockTeamManager, postgresRepo)

            const postgresGlobals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } },
                } as any,
            })
            await postgresManager.addGroupsToGlobals(postgresGlobals)

            // Second: get the fallback result (gRPC fails for everything)
            mockGrpc.groups.fetchGroupTypesByTeamIds.mockRejectedValue(new Error('down'))
            mockGrpc.groups.fetchGroupsByKeys.mockRejectedValue(new Error('down'))

            const fallbackGlobals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } },
                } as any,
            })
            await groupsManager.addGroupsToGlobals(fallbackGlobals)

            expect(fallbackGlobals.groups).toEqual(postgresGlobals.groups)
        })
    })
})
