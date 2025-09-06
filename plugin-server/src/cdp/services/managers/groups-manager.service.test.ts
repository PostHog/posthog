import { Hub } from '../../../types'
import { createHogExecutionGlobals } from '../../_tests/fixtures'
import { GroupsManagerService } from './groups-manager.service'

describe('Groups Manager', () => {
    jest.setTimeout(1000)
    let groupsManager: GroupsManagerService

    let mockGroupTypes: { team_id: number; group_type: string; group_type_index: number }[] = []
    let mockGroups: { team_id: number; group_key: string; group_type_index: number; group_properties?: any }[] = []

    const mockHub = {
        teamManager: {
            hasAvailableFeature: jest.fn(() => Promise.resolve(true)),
        },
        groupRepository: {
            fetchGroupTypesByTeamIds: jest.fn(),
            fetchGroupsByKeys: jest.fn(),
        },
    }

    beforeEach(() => {
        groupsManager = new GroupsManagerService(mockHub as unknown as Hub)
    })

    describe('unit tests', () => {
        beforeEach(() => {
            // Setup mock repository responses based on the repository interface format
            mockHub.groupRepository.fetchGroupTypesByTeamIds.mockImplementation((teamIds: number[]): Promise<any> => {
                const result: Record<string, { group_type: string; group_type_index: number }[]> = {}

                // Initialize empty arrays for all requested team IDs
                teamIds.forEach((teamId) => {
                    result[teamId.toString()] = []
                })

                // Add the mock data for teams that have group types
                mockGroupTypes.forEach((gt) => {
                    if (teamIds.includes(gt.team_id)) {
                        if (!result[gt.team_id.toString()]) {
                            result[gt.team_id.toString()] = []
                        }
                        result[gt.team_id.toString()].push({
                            group_type: gt.group_type,
                            group_type_index: gt.group_type_index,
                        })
                    }
                })

                return Promise.resolve(result)
            })

            mockHub.groupRepository.fetchGroupsByKeys.mockImplementation(
                (teamIds: number[], groupIndexes: number[], groupKeys: string[]): Promise<any> => {
                    const results = mockGroups.filter((group) => {
                        // Check if this group matches any of the requested combinations
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

            mockGroupTypes = [
                { team_id: 1, group_type: 'GroupA', group_type_index: 0 },
                { team_id: 1, group_type: 'GroupB', group_type_index: 1 },
                { team_id: 2, group_type: 'GroupA', group_type_index: 1 },
                { team_id: 2, group_type: 'GroupB', group_type_index: 2 },
                { team_id: 2, group_type: 'GroupC', group_type_index: 3 },
            ]

            mockGroups = []
        })

        it('does nothing if no group properties found', async () => {
            const globals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: {
                        $groups: { GroupA: 'id-1', GroupB: 'id-2' },
                    },
                } as any,
            })
            await groupsManager.enrichGroups([globals])

            expect(globals.groups).toMatchInlineSnapshot(`
                {
                  "GroupA": {
                    "id": "id-1",
                    "index": 0,
                    "properties": {},
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/0/id-1",
                  },
                  "GroupB": {
                    "id": "id-2",
                    "index": 1,
                    "properties": {},
                    "type": "GroupB",
                    "url": "http://localhost:8000/projects/1/groups/1/id-2",
                  },
                }
            `)
        })

        it('enriches simple groups', async () => {
            mockGroups = [
                { team_id: 1, group_type_index: 0, group_key: 'id-1', group_properties: { prop: 'value-1' } },
                { team_id: 1, group_type_index: 1, group_key: 'id-2', group_properties: { prop: 'value-2' } },
            ]
            const globals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: {
                        $groups: { GroupA: 'id-1', GroupB: 'id-2' },
                    },
                } as any,
            })
            await groupsManager.enrichGroups([globals])

            expect(globals.groups).toMatchInlineSnapshot(`
                {
                  "GroupA": {
                    "id": "id-1",
                    "index": 0,
                    "properties": {
                      "prop": "value-1",
                    },
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/0/id-1",
                  },
                  "GroupB": {
                    "id": "id-2",
                    "index": 1,
                    "properties": {
                      "prop": "value-2",
                    },
                    "type": "GroupB",
                    "url": "http://localhost:8000/projects/1/groups/1/id-2",
                  },
                }
            `)
        })

        it('enriches lots of groups', async () => {
            mockGroups = [
                { team_id: 1, group_type_index: 0, group_key: 'id-1', group_properties: { prop: 'value-team-1' } },
                { team_id: 2, group_type_index: 1, group_key: 'id-1', group_properties: { prop: 'value-team-2' } },
            ]

            const items = [
                // Should get both groups enriched
                createHogExecutionGlobals({
                    groups: undefined,
                    event: { properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } } } as any,
                }),
                // Should get its group enriched (via reference)
                createHogExecutionGlobals({
                    groups: undefined,
                    event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
                }),
                // Should get the right group for its team
                createHogExecutionGlobals({
                    groups: undefined,
                    project: { id: 2 } as any,
                    event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
                }),
            ]
            await groupsManager.enrichGroups(items)

            expect(items[0].groups).toMatchInlineSnapshot(`
                {
                  "GroupA": {
                    "id": "id-1",
                    "index": 0,
                    "properties": {
                      "prop": "value-team-1",
                    },
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/0/id-1",
                  },
                  "GroupB": {
                    "id": "id-2",
                    "index": 1,
                    "properties": {},
                    "type": "GroupB",
                    "url": "http://localhost:8000/projects/1/groups/1/id-2",
                  },
                }
            `)
            expect(items[1].groups).toMatchInlineSnapshot(`
                {
                  "GroupA": {
                    "id": "id-1",
                    "index": 0,
                    "properties": {
                      "prop": "value-team-1",
                    },
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/0/id-1",
                  },
                }
            `)
            expect(items[2].groups).toMatchInlineSnapshot(`
                {
                  "GroupA": {
                    "id": "id-1",
                    "index": 1,
                    "properties": {
                      "prop": "value-team-2",
                    },
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/1/id-1",
                  },
                }
            `)
        })

        it('handles invalid group properties', async () => {
            const globals = createHogExecutionGlobals({
                groups: undefined,
                event: {
                    properties: { $groups: { GroupA: { i: 'did', not: 'read', the: 'docs' }, GroupB: 'id-2' } },
                } as any,
            })
            await groupsManager.enrichGroups([globals])

            expect(mockHub.groupRepository.fetchGroupTypesByTeamIds).toHaveBeenCalledTimes(1)
            expect(mockHub.groupRepository.fetchGroupsByKeys).toHaveBeenCalledTimes(1)

            // Validate that only the correct ID values were used
            expect(mockHub.groupRepository.fetchGroupTypesByTeamIds).toHaveBeenCalledWith([1])
            expect(mockHub.groupRepository.fetchGroupsByKeys).toHaveBeenCalledWith([1], [1], ['id-2'])
        })
    })

    it('cached group type queries', async () => {
        const globals = [
            createHogExecutionGlobals({
                groups: undefined,
                project: { id: 1 } as any,
                event: { properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } } } as any,
            }),
            createHogExecutionGlobals({
                groups: undefined,
                project: { id: 2 } as any,
                event: { properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } } } as any,
            }),
        ]
        await groupsManager.enrichGroups(globals)
        expect(mockHub.groupRepository.fetchGroupTypesByTeamIds).toHaveBeenCalledTimes(1)
        expect(mockHub.groupRepository.fetchGroupsByKeys).toHaveBeenCalledTimes(1)
        mockHub.groupRepository.fetchGroupTypesByTeamIds.mockClear()
        mockHub.groupRepository.fetchGroupsByKeys.mockClear()

        await groupsManager.enrichGroups(globals)
        // Should use cache, not call repository again for the same teams
        expect(mockHub.groupRepository.fetchGroupTypesByTeamIds).toHaveBeenCalledTimes(0)
        expect(mockHub.groupRepository.fetchGroupsByKeys).toHaveBeenCalledTimes(1)
        mockHub.groupRepository.fetchGroupTypesByTeamIds.mockClear()
        mockHub.groupRepository.fetchGroupsByKeys.mockClear()

        globals.push(
            createHogExecutionGlobals({
                groups: undefined,
                project: { id: 3 } as any,
                event: { properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } } } as any,
            })
        )

        await groupsManager.enrichGroups(globals)
        // New team should trigger repository call, plus groups fetch
        expect(mockHub.groupRepository.fetchGroupTypesByTeamIds).toHaveBeenCalledTimes(1)
        expect(mockHub.groupRepository.fetchGroupsByKeys).toHaveBeenCalledTimes(1)
    })
})
