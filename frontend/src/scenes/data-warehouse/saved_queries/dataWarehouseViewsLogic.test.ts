import { expectLogic } from 'kea-test-utils'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'

describe('dataWarehouseViewsLogic', () => {
    let logic: ReturnType<typeof dataWarehouseViewsLogic.build>
    let databaseLogic: ReturnType<typeof databaseTableListLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/warehouse_saved_queries/': { results: [] },
            },
            delete: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/': [204],
            },
        })
        initKeaTests()
        databaseLogic = databaseTableListLogic()
        databaseLogic.mount()
        logic = dataWarehouseViewsLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        databaseLogic.unmount()
    })

    // Regression: delete must drop the view from the sidebar (via the loader's optimistic filter)
    // and refresh the picker (schema), but must NOT reload the whole list — that replaces every
    // row's identity and makes the tree flash.
    it('optimistically removes the view and refreshes the schema on delete, without reloading the list', async () => {
        // Let the mount's initial (empty) load settle before seeding, so the two don't race.
        await expectLogic(logic).toDispatchActions(['loadDataWarehouseSavedQueriesSuccess'])

        let listCalls = 0
        useMocks({
            get: {
                '/api/environments/:team_id/warehouse_saved_queries/': () => {
                    listCalls += 1
                    return [200, { results: [{ id: 'view-123', name: 'v' }] }]
                },
            },
            delete: { '/api/environments/:team_id/warehouse_saved_queries/:id/': [204] },
        })

        logic.actions.loadDataWarehouseSavedQueries()
        await expectLogic(logic).toDispatchActions(['loadDataWarehouseSavedQueriesSuccess'])
        expect(logic.values.dataWarehouseSavedQueries.map((view) => view.id)).toEqual(['view-123'])
        expect(listCalls).toBe(1)

        await expectLogic(logic, () => {
            logic.actions.deleteDataWarehouseSavedQuery('view-123')
        }).toDispatchActions(['deleteDataWarehouseSavedQuerySuccess', 'refreshDatabaseSchema'])

        // Row leaves via the loader's optimistic filter, and the list is not reloaded (no flash).
        expect(logic.values.dataWarehouseSavedQueries).toEqual([])
        expect(listCalls).toBe(1)
    })

    // Regression: a freshly materialized view showed as a plain view in the sidebar until a manual
    // refresh because is_materialized flips asynchronously and the list was fetched only once. The
    // poll must keep reloading until it settles, then stop (not loop forever).
    it('polls the saved-query list after materialization until is_materialized settles', async () => {
        jest.useFakeTimers()
        let isMaterialized = false
        let listCalls = 0
        useMocks({
            get: {
                '/api/environments/:team_id/warehouse_saved_queries/': () => {
                    listCalls += 1
                    return [200, { results: [{ id: 'view-1', name: 'v1', is_materialized: isMaterialized }] }]
                },
            },
            post: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/materialize/': [200],
            },
        })

        logic.actions.materializeDataWarehouseSavedQuery('view-1')
        await jest.advanceTimersByTimeAsync(0) // flush materialize + first reload
        expect(listCalls).toBe(1)
        // The view is marked materializing so the sidebar shows a spinner on its icon.
        expect(logic.values.materializingViewIds).toEqual(['view-1'])

        // Still materializing → poll reloads again after the interval.
        await jest.advanceTimersByTimeAsync(5000)
        expect(listCalls).toBe(2)
        expect(logic.values.materializingViewIds).toEqual(['view-1'])

        // Backend flips the flag; the next reload observes it settled.
        isMaterialized = true
        await jest.advanceTimersByTimeAsync(5000)
        expect(listCalls).toBe(3)
        // Settled → cleared, so the spinner flips to the materialized icon.
        expect(logic.values.materializingViewIds).toEqual([])

        // Settled → polling stops; advancing time triggers no further reloads.
        await jest.advanceTimersByTimeAsync(30000)
        expect(listCalls).toBe(3)

        jest.useRealTimers()
    })

    // Regression: the poll budget must be per-view. With a shared attempt counter, a view that
    // caps out clears every still-materializing view's spinner, so a second view started later
    // loses its spinner before its own materialization settles.
    it('gives each materializing view its own poll budget', async () => {
        jest.useFakeTimers()
        useMocks({
            get: {
                '/api/environments/:team_id/warehouse_saved_queries/': () => [
                    200,
                    {
                        results: [
                            { id: 'A', name: 'a', is_materialized: false },
                            { id: 'B', name: 'b', is_materialized: false },
                        ],
                    },
                ],
            },
            post: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/materialize/': [200],
            },
        })

        logic.actions.materializeDataWarehouseSavedQuery('A')
        await jest.advanceTimersByTimeAsync(0)
        // Let A burn several attempts before B starts.
        for (let i = 0; i < 3; i++) {
            await jest.advanceTimersByTimeAsync(5000)
        }
        logic.actions.materializeDataWarehouseSavedQuery('B')
        await jest.advanceTimersByTimeAsync(0)
        expect([...logic.values.materializingViewIds].sort()).toEqual(['A', 'B'])

        // Advance enough for A to hit its own cap (12 attempts) but not B's (started 4 ticks later).
        for (let i = 0; i < 8; i++) {
            await jest.advanceTimersByTimeAsync(5000)
        }
        // A capped out and its spinner cleared; B is still materializing on its own budget.
        expect(logic.values.materializingViewIds).toEqual(['B'])

        jest.useRealTimers()
    })
})
