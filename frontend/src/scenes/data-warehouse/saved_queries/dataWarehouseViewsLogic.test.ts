import { expectLogic } from 'kea-test-utils'

// Imported from the source module rather than the `@posthog/lemon-ui` barrel so the spy replaces
// `.error` on the same `lemonToast` singleton the logic calls at runtime.
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { dataWarehouseViewsLogic } from './dataWarehouseViewsLogic'

const rejection = {
    type: 'validation_error',
    code: 'invalid_input',
    detail: "Can't refresh every 1 day: a view or endpoint built on this one refreshes every 15 minutes. Pick 15 minutes instead.",
    attr: null,
}

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

    // Regression: deleting a view that's already gone (double DELETE, stale list, double-click) is
    // the outcome the user asked for, so a 404 must resolve as success — not throw an error toast.
    it('treats a 404 on delete as success', async () => {
        await expectLogic(logic).toDispatchActions(['loadDataWarehouseSavedQueriesSuccess'])

        useMocks({
            get: {
                '/api/environments/:team_id/warehouse_saved_queries/': () => [
                    200,
                    { results: [{ id: 'view-404', name: 'v' }] },
                ],
            },
            delete: { '/api/environments/:team_id/warehouse_saved_queries/:id/': [404, { detail: 'Not found.' }] },
        })

        logic.actions.loadDataWarehouseSavedQueries()
        await expectLogic(logic).toDispatchActions(['loadDataWarehouseSavedQueriesSuccess'])

        await expectLogic(logic, () => {
            logic.actions.deleteDataWarehouseSavedQuery('view-404')
        })
            .toDispatchActions(['deleteDataWarehouseSavedQuerySuccess'])
            .toNotHaveDispatchedActions(['deleteDataWarehouseSavedQueryFailure'])

        expect(logic.values.dataWarehouseSavedQueries).toEqual([])
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
                '/api/projects/:team_id/warehouse_saved_queries/:id/materialize/': [200],
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

    // Regression: the picked cadence must reach the server. Before the frequency was part of the
    // request the action always enabled materialization daily, which the server refuses outright
    // for any view a sub-daily consumer reads.
    it('materializes at the requested sync frequency', async () => {
        let requestedFrequency: string | undefined
        useMocks({
            post: {
                '/api/projects/:team_id/warehouse_saved_queries/:id/materialize/': async ({ request }) => {
                    requestedFrequency = ((await request.json()) as { sync_frequency?: string }).sync_frequency
                    return [200]
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.materializeDataWarehouseSavedQuery('view-1', '1hour')
        }).toFinishAllListeners()

        expect(requestedFrequency).toBe('1hour')
    })

    // Regression: a cadence the lineage can't support is rejected with a message naming the one to
    // pick instead. A generic toast leaves the user with a button that fails and no way forward.
    it.each([
        [
            'materialize',
            () => logic.actions.materializeDataWarehouseSavedQuery('view-1', '24hour'),
            { post: { '/api/projects/:team_id/warehouse_saved_queries/:id/materialize/': [400, rejection] } },
        ],
        [
            'sync frequency update',
            () => logic.actions.updateDataWarehouseSavedQuery({ id: 'view-1', sync_frequency: '24hour' }),
            { patch: { '/api/environments/:team_id/warehouse_saved_queries/:id/': [400, rejection] } },
        ],
    ])('surfaces why the server rejected the cadence on %s', async (_name, act, mocks) => {
        const toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => ({ id: 'x' }) as any)
        useMocks(mocks)

        await expectLogic(logic, act).toFinishAllListeners()

        expect(toastErrorSpy).toHaveBeenCalledWith(rejection.detail)
        toastErrorSpy.mockRestore()
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
                '/api/projects/:team_id/warehouse_saved_queries/:id/materialize/': [200],
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

    // Regression: the config must be stored before materialization is enabled, or the first run
    // (triggered by the materialize call) rebuilds the table as a full refresh and ignores the
    // incremental settings the user picked.
    it('persists the incremental config before enabling materialization', async () => {
        const calls: string[] = []
        let patchBody: Record<string, any> | undefined
        useMocks({
            patch: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/': async ({ request }) => {
                    calls.push('update')
                    patchBody = (await request.json()) as Record<string, any>
                    return [200, { id: 'view-1', name: 'v1' }]
                },
            },
            post: {
                '/api/projects/:team_id/warehouse_saved_queries/:id/materialize/': () => {
                    calls.push('materialize')
                    return [200]
                },
            },
        })

        const incremental = {
            enabled: true,
            incremental_key: 'timestamp',
            unique_key: ['event', 'timestamp'],
            lookback_seconds: 3600,
        }
        await expectLogic(logic, () => {
            logic.actions.materializeDataWarehouseSavedQuery('view-1', '24hour', incremental)
        }).toFinishAllListeners()

        expect(calls).toEqual(['update', 'materialize'])
        expect(patchBody?.incremental).toEqual(incremental)
    })

    // Regression: when the config write is rejected (the server re-checks eligibility), the view
    // must not be materialized anyway - that would silently start full-refresh runs the user did
    // not ask for. The server's reason has to reach the user.
    it('does not enable materialization when saving the incremental config fails', async () => {
        const toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => ({ id: 'x' }) as any)
        let materializeCalls = 0
        const incrementalRejection = {
            type: 'validation_error',
            code: 'invalid_input',
            detail: 'LIMIT cannot be incremental. A window cannot be recomputed on its own.',
            attr: 'incremental',
        }
        useMocks({
            patch: {
                '/api/environments/:team_id/warehouse_saved_queries/:id/': [400, incrementalRejection],
            },
            post: {
                '/api/projects/:team_id/warehouse_saved_queries/:id/materialize/': () => {
                    materializeCalls += 1
                    return [200]
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions.materializeDataWarehouseSavedQuery('view-1', '24hour', {
                enabled: true,
                incremental_key: 'timestamp',
                unique_key: ['id'],
                lookback_seconds: 0,
            })
        }).toFinishAllListeners()

        expect(materializeCalls).toBe(0)
        expect(toastErrorSpy).toHaveBeenCalledWith(incrementalRejection.detail)
        toastErrorSpy.mockRestore()
    })
})
