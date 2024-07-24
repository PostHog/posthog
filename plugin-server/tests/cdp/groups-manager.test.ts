import { GroupsManager } from '../../src/cdp/groups-manager'
import { Hub } from '../../src/types'
import { createHogExecutionGlobals, insertHogFunction as _insertHogFunction } from './fixtures'

describe('Groups Manager', () => {
    jest.setTimeout(1000)
    let groupsManager: GroupsManager

    beforeEach(() => {
        groupsManager = new GroupsManager({} as Hub)
    })

    describe('unit tests', () => {
        beforeEach(() => {
            groupsManager['fetchGroupTypesMapping'] = jest.fn(() =>
                Promise.resolve({
                    [`1:GroupA`]: 0,
                    [`1:GroupB`]: 1,
                    [`2:GroupA`]: 1,
                    [`2:GroupB`]: 2,
                    [`2:GroupC`]: 3,
                })
            )
            groupsManager['fetchGroupProperties'] = jest.fn(() => Promise.resolve([]))
        })

        it('does nothing if no group properties found', async () => {
            const globals = createHogExecutionGlobals({
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
                    "teamId": 1,
                    "type": "GroupA",
                    "url": "http://localhost:8000/projects/1/groups/0/id-1",
                  },
                  "GroupB": Object {
                    "id": "id-2",
                    "index": 1,
                    "properties": Object {},
                    "teamId": 1,
                    "type": "GroupB",
                    "url": "http://localhost:8000/projects/1/groups/1/id-2",
                  },
                }
            `)
        })

        it('enriches simple groups', async () => {
            groupsManager['fetchGroupProperties'] = jest.fn(() =>
                Promise.resolve([
                    { team_id: 1, group_type_index: 1, group_key: 'id-2', group_properties: { prop: 'value-2' } },
                    { team_id: 1, group_type_index: 0, group_key: 'id-1', group_properties: { prop: 'value-1' } },
                ])
            )
            const globals = createHogExecutionGlobals({
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
            groupsManager['fetchGroupProperties'] = jest.fn(() =>
                Promise.resolve([
                    { team_id: 1, group_type_index: 0, group_key: 'id-1', group_properties: { prop: 'value-team-1' } },
                    { team_id: 2, group_type_index: 1, group_key: 'id-1', group_properties: { prop: 'value-team-2' } },
                ])
            )

            const items = [
                // Should get both groups enriched
                createHogExecutionGlobals({
                    event: { properties: { $groups: { GroupA: 'id-1', GroupB: 'id-2' } } } as any,
                }),
                // Should get its group enriched (via reference)
                createHogExecutionGlobals({
                    event: { properties: { $groups: { GroupA: 'id-1' } } } as any,
                }),
                // Should get the right group for its team
                createHogExecutionGlobals({
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
                    "teamId": 1,
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
})
