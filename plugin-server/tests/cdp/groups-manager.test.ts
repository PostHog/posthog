import { GroupsManager } from '../../src/cdp/groups-manager'
import { Hub } from '../../src/types'
import { createHogExecutionGlobals, insertHogFunction as _insertHogFunction } from './fixtures'

describe('Groups Manager', () => {
    jest.setTimeout(1000)
    let groupsManager: GroupsManager

    let mockGroupTypes: { team_id: number; group_type: string; group_type_index: number }[] = []
    let mockGroups: { team_id: number; group_key: string; group_type_index: number; group_properties?: any }[] = []

    const mockHub = {
        postgres: {
            query: jest.fn(),
        },
        organizationManager: {
            hasAvailableFeature: jest.fn(() => Promise.resolve(true)),
        },
    }

    beforeEach(() => {
        groupsManager = new GroupsManager(mockHub as unknown as Hub)
    })

    describe('unit tests', () => {
        beforeEach(() => {
            mockHub.postgres.query.mockImplementation((_, query): Promise<any> => {
                if (query.includes('posthog_grouptypemapping')) {
                    return Promise.resolve({ rows: mockGroupTypes })
                }

                if (query.includes('posthog_group')) {
                    return Promise.resolve({ rows: mockGroups })
                }
                return Promise.resolve({
                    rows: [],
                })
            })

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
                Object {
                  "GroupA": Object {
                    "id": "id-1",
                    "index": 0,
                    "properties": Object {},
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/0/id-1",
                  },
                  "GroupB": Object {
                    "id": "id-2",
                    "index": 1,
                    "properties": Object {},
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
                Object {
                  "GroupA": Object {
                    "id": "id-1",
                    "index": 0,
                    "properties": Object {
                      "prop": "value-1",
                    },
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/0/id-1",
                  },
                  "GroupB": Object {
                    "id": "id-2",
                    "index": 1,
                    "properties": Object {
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
                Object {
                  "GroupA": Object {
                    "id": "id-1",
                    "index": 0,
                    "properties": Object {
                      "prop": "value-team-1",
                    },
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/0/id-1",
                  },
                  "GroupB": Object {
                    "id": "id-2",
                    "index": 1,
                    "properties": Object {},
                    "type": "GroupB",
                    "url": "http://localhost:8000/projects/1/groups/1/id-2",
                  },
                }
            `)
            expect(items[1].groups).toMatchInlineSnapshot(`
                Object {
                  "GroupA": Object {
                    "id": "id-1",
                    "index": 0,
                    "properties": Object {
                      "prop": "value-team-1",
                    },
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/0/id-1",
                  },
                }
            `)
            expect(items[2].groups).toMatchInlineSnapshot(`
                Object {
                  "GroupA": Object {
                    "id": "id-1",
                    "index": 1,
                    "properties": Object {
                      "prop": "value-team-2",
                    },
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/1/id-1",
                  },
                }
            `)
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
        expect(mockHub.postgres.query).toHaveBeenCalledTimes(2)
        mockHub.postgres.query.mockClear()

        await groupsManager.enrichGroups(globals)
        expect(mockHub.postgres.query).toHaveBeenCalledTimes(1)
        mockHub.postgres.query.mockClear()

        globals.push(
            createHogExecutionGlobals({
                groups: undefined,
                project: { id: 3 } as any,
                event: { properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } } } as any,
            })
        )

        await groupsManager.enrichGroups(globals)
        expect(mockHub.postgres.query).toHaveBeenCalledTimes(2)
    })
})
