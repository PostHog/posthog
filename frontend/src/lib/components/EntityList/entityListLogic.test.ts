import { BuiltLogic } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { Scene } from 'scenes/sceneTypes'

import { initKeaTests } from '~/test/init'

import { entityListLogic, mountedEntityListRows, refreshEntityList } from './entityListLogic'
import { registerEntityList } from './entityListRegistry'
import { EntityListDefinition, EntityListQuery } from './types'

interface Widget extends Record<string, any> {
    id: string
    name: string
}

const WIDGETS: Widget[] = [
    { id: '1', name: 'Alpha' },
    { id: '2', name: 'Beta' },
    { id: '3', name: 'Gamma' },
]

const CLIENT_URL = '/test-client-widgets'
const SERVER_URL = '/test-server-widgets'

function makeDefinition(overrides: Partial<EntityListDefinition<Widget>>): EntityListDefinition<Widget> {
    return {
        type: 'test_widget',
        scene: 'TestWidgets' as Scene,
        url: CLIENT_URL,
        name: 'Widgets',
        nouns: ['widget', 'widgets'],
        mode: 'client',
        load: async () => ({ results: WIDGETS }),
        nameColumn: { render: (widget) => widget.name },
        columns: [],
        ...overrides,
    }
}

describe('entityListLogic', () => {
    let logic: BuiltLogic<any>

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('client mode', () => {
        let load: jest.Mock<Promise<{ results: Widget[] }>, [EntityListQuery]>

        beforeEach(async () => {
            load = jest.fn(async (_query: EntityListQuery) => ({ results: WIDGETS }))
            logic = entityListLogic({
                definition: makeDefinition({
                    type: 'test_client_widget',
                    load,
                    search: { placeholder: 'Search widgets...', keys: ['name'] },
                }),
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('narrows results in the browser without refetching', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ search: 'Beta' })
            }).toFinishAllListeners()

            expect(logic.values.results).toEqual([WIDGETS[1]])
            expect(logic.values.count).toBe(1)
            expect(load).toHaveBeenCalledTimes(1)
        })

        it('reports no matches as narrowed rather than empty', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ search: 'nothing like this' })
            }).toFinishAllListeners()

            expect(logic.values.results).toEqual([])
            expect(logic.values.isNarrowed).toBe(true)
            expect(logic.values.isEmpty).toBe(false)
        })
    })

    describe('server mode', () => {
        let load: jest.Mock<Promise<{ results: Widget[]; count: number }>, [EntityListQuery]>

        beforeEach(async () => {
            load = jest.fn(async (_query: EntityListQuery) => ({ results: WIDGETS, count: 42 }))
            router.actions.push(SERVER_URL)
            logic = entityListLogic({
                definition: makeDefinition({
                    type: 'test_server_widget',
                    url: SERVER_URL,
                    mode: 'server',
                    pageSize: 10,
                    defaultOrderBy: '-created_at',
                    load,
                    search: { placeholder: 'Search widgets...' },
                }),
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('sends paging and ordering to the loader and takes the count from the response', () => {
            expect(load).toHaveBeenLastCalledWith({
                search: '',
                page: 1,
                limit: 10,
                offset: 0,
                orderBy: '-created_at',
            })
            expect(logic.values.count).toBe(42)
        })

        it('refetches from the first page when the search changes', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ page: 3 })
            }).toFinishAllListeners()
            expect(load).toHaveBeenLastCalledWith(expect.objectContaining({ page: 3, offset: 20 }))

            await expectLogic(logic, () => {
                logic.actions.setFilters({ search: 'alpha' })
            }).toFinishAllListeners()
            expect(load).toHaveBeenLastCalledWith(expect.objectContaining({ search: 'alpha', page: 1, offset: 0 }))
        })

        it('round-trips search, page and ordering through the URL', async () => {
            await expectLogic(logic, () => {
                logic.actions.setFilters({ search: 'alpha', orderBy: 'name' })
            }).toFinishAllListeners()
            expect(router.values.searchParams).toEqual({ search: 'alpha', order_by: 'name' })

            await expectLogic(logic, () => {
                router.actions.push(SERVER_URL, { search: 'beta', page: '2' })
            }).toFinishAllListeners()
            expect(logic.values.filters).toEqual({ search: 'beta', page: 2, orderBy: '-created_at' })
        })

        it('is reachable by type once registered', async () => {
            const definition = logic.props.definition
            registerEntityList(definition)

            expect(mountedEntityListRows<Widget>(definition.type)).toEqual(WIDGETS)

            await expectLogic(logic, () => {
                refreshEntityList(definition.type)
            }).toFinishAllListeners()
            expect(load).toHaveBeenCalledTimes(2)
        })
    })
})
