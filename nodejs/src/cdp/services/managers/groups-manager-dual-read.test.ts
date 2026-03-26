import { TeamManager } from '~/utils/team-manager'
import { GroupRepository } from '~/worker/ingestion/groups/repositories/group-repository.interface'

import { PersonHogClient } from '../../../personhog/client'
import { DualReadGroupRepository } from '../../../personhog/dual-read-group-repository'
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

function createMockGrpcClient(
    groupTypes: typeof MOCK_GROUP_TYPES,
    groups: typeof MOCK_GROUPS
): jest.Mocked<
    Pick<
        PersonHogClient,
        'fetchGroup' | 'fetchGroupsByKeys' | 'fetchGroupTypesByTeamIds' | 'fetchGroupTypesByProjectIds'
    >
> {
    const mock = {
        fetchGroup: jest.fn(),
        fetchGroupsByKeys: jest.fn() as jest.Mock,
        fetchGroupTypesByTeamIds: jest.fn() as jest.Mock,
        fetchGroupTypesByProjectIds: jest.fn() as jest.Mock,
    }

    mock.fetchGroupTypesByTeamIds.mockImplementation((teamIds: number[]) => {
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

    mock.fetchGroupsByKeys.mockImplementation((teamIds: number[], groupIndexes: number[], groupKeys: string[]) => {
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
    })

    return mock
}

describe('GroupsManagerService + DualReadGroupRepository integration', () => {
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

            const dualRead = new DualReadGroupRepository(
                mockPostgres,
                mockGrpc as unknown as PersonHogClient,
                rolloutPercentage,
                'test'
            )
            groupsManager = new GroupsManagerService(mockTeamManager, dualRead)
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
                expect(mockGrpc.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([TEAM_1])
                expect(mockGrpc.fetchGroupsByKeys).toHaveBeenCalled()
                expect(mockPostgres.fetchGroupTypesByTeamIds).not.toHaveBeenCalled()
                expect(mockPostgres.fetchGroupsByKeys).not.toHaveBeenCalled()
            } else {
                expect(mockPostgres.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([TEAM_1])
                expect(mockPostgres.fetchGroupsByKeys).toHaveBeenCalled()
                expect(mockGrpc.fetchGroupTypesByTeamIds).not.toHaveBeenCalled()
                expect(mockGrpc.fetchGroupsByKeys).not.toHaveBeenCalled()
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

    describe('grpc fallback to postgres on error', () => {
        let mockPostgres: jest.Mocked<GroupRepository>
        let mockGrpc: ReturnType<typeof createMockGrpcClient>
        let groupsManager: GroupsManagerService

        beforeEach(() => {
            jest.restoreAllMocks()
            mockHasAvailableFeature.mockReturnValue(Promise.resolve(true))
            mockPostgres = createMockPostgres(MOCK_GROUP_TYPES, MOCK_GROUPS)
            mockGrpc = createMockGrpcClient(MOCK_GROUP_TYPES, MOCK_GROUPS)

            const dualRead = new DualReadGroupRepository(
                mockPostgres,
                mockGrpc as unknown as PersonHogClient,
                100,
                'test'
            )
            groupsManager = new GroupsManagerService(mockTeamManager, dualRead)
        })

        it('falls back to postgres when gRPC fetchGroupTypesByTeamIds fails', async () => {
            mockGrpc.fetchGroupTypesByTeamIds.mockRejectedValue(new Error('connection refused'))

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
            expect(mockGrpc.fetchGroupTypesByTeamIds).toHaveBeenCalled()
            // Postgres was called as fallback
            expect(mockPostgres.fetchGroupTypesByTeamIds).toHaveBeenCalled()
        })

        it('falls back to postgres when gRPC fetchGroupsByKeys fails', async () => {
            mockGrpc.fetchGroupsByKeys.mockRejectedValue(new Error('timeout'))

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
            expect(mockGrpc.fetchGroupsByKeys).toHaveBeenCalled()
            // Postgres fetchGroupsByKeys was called as fallback
            expect(mockPostgres.fetchGroupsByKeys).toHaveBeenCalled()
        })

        it('produces identical output on fallback as on direct postgres path', async () => {
            // First: get the postgres-only result
            const postgresRepo = new DualReadGroupRepository(
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
            mockGrpc.fetchGroupTypesByTeamIds.mockRejectedValue(new Error('down'))
            mockGrpc.fetchGroupsByKeys.mockRejectedValue(new Error('down'))

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
