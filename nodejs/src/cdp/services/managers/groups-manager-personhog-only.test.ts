import { TeamManager } from '~/utils/team-manager'

import { PersonHogClient } from '../../../ingestion/personhog/client'
import { PersonHogOnlyGroupRepository } from '../../../ingestion/personhog/personhog-only-group-repository'
import { GroupTypeIndex, ProjectId, TeamId } from '../../../types'
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

type MockPersonHogClient = {
    groups: jest.Mocked<
        Pick<
            PersonHogClient['groups'],
            'fetchGroup' | 'fetchGroupsByKeys' | 'fetchGroupTypesByTeamIds' | 'fetchGroupTypesByProjectIds'
        >
    >
    persons: jest.Mocked<Pick<PersonHogClient['persons'], 'fetchPersonsByDistinctIds' | 'fetchPersonsByPersonIds'>>
}

function createMockGrpcClient(groupTypes: typeof MOCK_GROUP_TYPES, groups: typeof MOCK_GROUPS): MockPersonHogClient {
    const mock: MockPersonHogClient = {
        groups: {
            fetchGroup: jest.fn(),
            fetchGroupsByKeys: jest.fn(),
            fetchGroupTypesByTeamIds: jest.fn(),
            fetchGroupTypesByProjectIds: jest.fn(),
        },
        persons: {
            fetchPersonsByDistinctIds: jest.fn(),
            fetchPersonsByPersonIds: jest.fn(),
        },
    }

    mock.groups.fetchGroupTypesByTeamIds.mockImplementation((teamIds: number[]) => {
        const result: Record<string, { group_type: string; group_type_index: GroupTypeIndex }[]> = {}
        for (const gt of groupTypes) {
            if (teamIds.includes(gt.team_id)) {
                if (!result[gt.team_id.toString()]) {
                    result[gt.team_id.toString()] = []
                }
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

describe('GroupsManagerService + PersonHogOnlyGroupRepository', () => {
    jest.setTimeout(1000)

    const mockHasAvailableFeature = jest.fn(() => Promise.resolve(true))
    const mockTeamManager = {
        hasAvailableFeature: mockHasAvailableFeature,
    } as unknown as TeamManager

    let mockGrpc: MockPersonHogClient
    let groupsManager: GroupsManagerService

    beforeEach(() => {
        jest.restoreAllMocks()
        mockHasAvailableFeature.mockReturnValue(Promise.resolve(true))
        mockGrpc = createMockGrpcClient(MOCK_GROUP_TYPES, MOCK_GROUPS)

        const repo = new PersonHogOnlyGroupRepository(mockGrpc as unknown as PersonHogClient, 'test')
        groupsManager = new GroupsManagerService(mockTeamManager, repo)
    })

    it('enriches simple groups via gRPC', async () => {
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

        expect(mockGrpc.groups.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([TEAM_1])
        expect(mockGrpc.groups.fetchGroupsByKeys).toHaveBeenCalled()
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

    it('handles gRPC omitting keys for teams without group types', async () => {
        const TEAM_3 = 3 as TeamId
        const emptyGrpc = createMockGrpcClient([], [])
        emptyGrpc.groups.fetchGroupTypesByTeamIds.mockResolvedValue({})

        const repo = new PersonHogOnlyGroupRepository(emptyGrpc as unknown as PersonHogClient, 'test')
        const manager = new GroupsManagerService(
            { hasAvailableFeature: jest.fn().mockResolvedValue(true) } as unknown as TeamManager,
            repo
        )

        const globals = createHogExecutionGlobals({
            groups: undefined,
            project: { id: TEAM_3 } as any,
            event: {
                properties: { $groups: { UnknownType: 'some-key' } },
            } as any,
        })

        await manager.addGroupsToGlobals(globals)

        expect(globals.groups).toEqual({})
        expect(emptyGrpc.groups.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([TEAM_3])
        expect(emptyGrpc.groups.fetchGroupsByKeys).not.toHaveBeenCalled()
    })

    describe('gRPC errors propagate without fallback', () => {
        it('propagates gRPC error on fetchGroupTypesByTeamIds', async () => {
            mockGrpc.groups.fetchGroupTypesByTeamIds.mockRejectedValue(new Error('connection refused'))

            const globals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: { $groups: { GroupA: 'id-1' } },
                } as any,
            })

            await expect(groupsManager.addGroupsToGlobals(globals)).rejects.toThrow('connection refused')
        })

        it('propagates gRPC error on fetchGroupsByKeys', async () => {
            mockGrpc.groups.fetchGroupsByKeys.mockRejectedValue(new Error('timeout'))

            const globals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: { $groups: { GroupA: 'id-1' } },
                } as any,
            })

            await expect(groupsManager.addGroupsToGlobals(globals)).rejects.toThrow('timeout')
        })
    })

    describe('write operations throw', () => {
        it('throws on insertGroup', () => {
            const repo = new PersonHogOnlyGroupRepository(mockGrpc as unknown as PersonHogClient, 'test')
            expect(() => repo.insertGroup(1 as TeamId, 0 as GroupTypeIndex, 'key', {}, {} as any, {}, {})).toThrow(
                'does not support write operations'
            )
        })

        it('throws on insertGroupType', () => {
            const repo = new PersonHogOnlyGroupRepository(mockGrpc as unknown as PersonHogClient, 'test')
            expect(() => repo.insertGroupType(1 as TeamId, 1 as ProjectId, 'type', 0)).toThrow(
                'does not support write operations'
            )
        })

        it('throws on inTransaction', () => {
            const repo = new PersonHogOnlyGroupRepository(mockGrpc as unknown as PersonHogClient, 'test')
            expect(() => repo.inTransaction('test', async () => {})).toThrow('does not support write operations')
        })
    })
})
