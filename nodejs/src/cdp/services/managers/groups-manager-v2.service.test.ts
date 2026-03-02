import { TeamManager } from '~/utils/team-manager'
import { GroupRepository } from '~/worker/ingestion/groups/repositories/group-repository.interface'

import { createHogExecutionGlobals } from '../../_tests/fixtures'
import { GroupsManagerServiceV2 } from './groups-manager-v2.service'

describe('Groups Manager V2', () => {
    jest.setTimeout(1000)
    let groupsManager: GroupsManagerServiceV2

    let mockGroupTypes: { team_id: number; group_type: string; group_type_index: number }[] = []
    let mockGroups: { team_id: number; group_key: string; group_type_index: number; group_properties?: any }[] = []

    const mockHasAvailableFeature = jest.fn(() => Promise.resolve(true))
    const mockFetchGroupTypesByTeamIds = jest.fn()
    const mockFetchGroupsByKeys = jest.fn()

    const mockTeamManager = {
        hasAvailableFeature: mockHasAvailableFeature,
    } as unknown as TeamManager

    const mockGroupRepository = {
        fetchGroupTypesByTeamIds: mockFetchGroupTypesByTeamIds,
        fetchGroupsByKeys: mockFetchGroupsByKeys,
    } as unknown as GroupRepository

    beforeEach(() => {
        jest.restoreAllMocks()
        mockHasAvailableFeature.mockReturnValue(Promise.resolve(true))
        groupsManager = new GroupsManagerServiceV2(mockTeamManager, mockGroupRepository)

        mockFetchGroupTypesByTeamIds.mockImplementation((teamIds: number[]): Promise<any> => {
            const result: Record<string, { group_type: string; group_type_index: number }[]> = {}

            teamIds.forEach((teamId) => {
                result[teamId.toString()] = []
            })

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

        mockFetchGroupsByKeys.mockImplementation(
            (teamIds: number[], groupIndexes: number[], groupKeys: string[]): Promise<any> => {
                const results = mockGroups.filter((group) => {
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

    it('sets empty properties when no group properties found in DB', async () => {
        const globals = createHogExecutionGlobals({
            groups: undefined,
            event: {
                properties: {
                    $groups: { GroupA: 'id-1', GroupB: 'id-2' },
                },
            } as any,
        })
        await groupsManager.addGroupsToGlobals(globals)

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
        await groupsManager.addGroupsToGlobals(globals)

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

    it('enriches multiple items concurrently via Promise.all', async () => {
        mockGroups = [
            { team_id: 1, group_type_index: 0, group_key: 'id-1', group_properties: { prop: 'value-team-1' } },
            { team_id: 2, group_type_index: 1, group_key: 'id-1', group_properties: { prop: 'value-team-2' } },
        ]

        const items = [
            createHogExecutionGlobals({
                groups: undefined,
                event: { properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } } } as any,
            }),
            createHogExecutionGlobals({
                groups: undefined,
                event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
            }),
            createHogExecutionGlobals({
                groups: undefined,
                project: { id: 2 } as any,
                event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
            }),
        ]
        await Promise.all(items.map((item) => groupsManager.addGroupsToGlobals(item)))

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
        await groupsManager.addGroupsToGlobals(globals)

        expect(mockFetchGroupTypesByTeamIds).toHaveBeenCalledTimes(1)
        expect(mockFetchGroupsByKeys).toHaveBeenCalledTimes(1)

        expect(mockFetchGroupTypesByTeamIds).toHaveBeenCalledWith([1])
        expect(mockFetchGroupsByKeys).toHaveBeenCalledWith([1], [1], ['id-2'])
    })

    it.each([
        { $groups: undefined, desc: 'missing' },
        { $groups: null, desc: 'null' },
        { $groups: 'not-an-object', desc: 'a string' },
        { $groups: {}, desc: 'an empty object' },
    ])('skips group type loading when $groups is $desc', async ({ $groups }) => {
        const globals = createHogExecutionGlobals({
            groups: undefined,
            event: { properties: { $groups } } as any,
        })
        await groupsManager.addGroupsToGlobals(globals)

        expect(globals.groups).toEqual({})
        expect(mockFetchGroupTypesByTeamIds).not.toHaveBeenCalled()
        expect(mockFetchGroupsByKeys).not.toHaveBeenCalled()
    })

    it('skips enrichment when groups already set', async () => {
        const existingGroups = { SomeGroup: { id: 'existing', index: 0, type: 'SomeGroup', url: '', properties: {} } }
        const globals = createHogExecutionGlobals({
            groups: existingGroups,
            event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
        })
        await groupsManager.addGroupsToGlobals(globals)

        expect(globals.groups).toBe(existingGroups)
        expect(mockFetchGroupTypesByTeamIds).not.toHaveBeenCalled()
    })

    it('sets empty groups when team has no group_analytics feature', async () => {
        mockHasAvailableFeature.mockResolvedValue(false)
        const globals = createHogExecutionGlobals({
            groups: undefined,
            event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
        })
        await groupsManager.addGroupsToGlobals(globals)

        expect(globals.groups).toEqual({})
        expect(mockFetchGroupTypesByTeamIds).not.toHaveBeenCalled()
    })

    it('caches group type and property lookups across calls', async () => {
        mockGroups = [{ team_id: 1, group_type_index: 0, group_key: 'id-1', group_properties: { prop: 'value-1' } }]

        const globals1 = createHogExecutionGlobals({
            groups: undefined,
            project: { id: 1 } as any,
            event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
        })
        await groupsManager.addGroupsToGlobals(globals1)
        expect(mockFetchGroupTypesByTeamIds).toHaveBeenCalledTimes(1)
        expect(mockFetchGroupsByKeys).toHaveBeenCalledTimes(1)
        mockFetchGroupTypesByTeamIds.mockClear()
        mockFetchGroupsByKeys.mockClear()

        // Second call with same data - both group types AND properties are cached
        const globals2 = createHogExecutionGlobals({
            groups: undefined,
            project: { id: 1 } as any,
            event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
        })
        await groupsManager.addGroupsToGlobals(globals2)
        expect(mockFetchGroupTypesByTeamIds).toHaveBeenCalledTimes(0)
        expect(mockFetchGroupsByKeys).toHaveBeenCalledTimes(0)
    })

    it('respects clear() to reset all caches', async () => {
        const globals1 = createHogExecutionGlobals({
            groups: undefined,
            project: { id: 1 } as any,
            event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
        })
        await groupsManager.addGroupsToGlobals(globals1)
        mockFetchGroupTypesByTeamIds.mockClear()
        mockFetchGroupsByKeys.mockClear()

        groupsManager.clear()

        const globals2 = createHogExecutionGlobals({
            groups: undefined,
            project: { id: 1 } as any,
            event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
        })
        await groupsManager.addGroupsToGlobals(globals2)
        expect(mockFetchGroupTypesByTeamIds).toHaveBeenCalledTimes(1)
        expect(mockFetchGroupsByKeys).toHaveBeenCalledTimes(1)
    })
})
