import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { DataWarehouseSavedQuery } from '~/types'

import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'

import { PAGE_SIZE, viewsTabLogic } from './viewsTabLogic'

function buildView(id: string, isMaterialized: boolean): DataWarehouseSavedQuery {
    return {
        id,
        name: id,
        columns: [],
        managed_viewset_kind: null,
        latest_error: null,
        is_materialized: isMaterialized,
        created_at: '2024-01-01T00:00:00Z',
    }
}

describe('viewsTabLogic', () => {
    let logic: ReturnType<typeof viewsTabLogic.build>
    let runHistoryRequests: string[]

    beforeEach(async () => {
        runHistoryRequests = []
        const views = [
            ...Array.from({ length: PAGE_SIZE + 1 }, (_, i) => buildView(`mat-${i}`, true)),
            buildView('plain-a', false),
            buildView('plain-b', false),
        ]
        useMocks({
            get: {
                '/api/projects/:team_id/endpoints/': { count: 0, results: [] },
                '/api/projects/:team_id/endpoints/:name/versions/': { count: 0, results: [] },
                '/api/environments/:team_id/warehouse_saved_queries/': { count: views.length, results: views },
                '/api/environments/:team_id/data_modeling_nodes/': { count: 0, results: [] },
                '/api/environments/:team_id/data_modeling_edges/': { count: 0, results: [] },
                '/api/environments/:team_id/warehouse_saved_queries/:id/run_history/': (req) => {
                    runHistoryRequests.push(String(req.params.id))
                    return [200, { run_history: [] }]
                },
            },
            post: { '/api/environments/:team_id/query/': { tables: {} } },
            delete: { '/api/environments/:team_id/warehouse_saved_queries/:id/': [204, null] },
        })
        initKeaTests()
        logic = viewsTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    it('loads run history only for the materialized views on the visible page', () => {
        expect(logic.values.visibleViews).toHaveLength(PAGE_SIZE)
        expect(runHistoryRequests).toHaveLength(PAGE_SIZE)
        expect(runHistoryRequests.every((id) => id.startsWith('mat-'))).toBe(true)
    })

    it('narrows the list by type and resets to the first page', async () => {
        logic.actions.setPage(2)
        expect(logic.values.currentPage).toEqual(2)

        logic.actions.setTypeFilter('view')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.currentPage).toEqual(1)
        expect(logic.values.filteredViews.map((view) => view.id)).toEqual(['plain-a', 'plain-b'])
    })

    it('search and type filter compose', async () => {
        logic.actions.setTypeFilter('materialized')
        logic.actions.setSearchTerm('mat-1')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filteredViews.map((view) => view.id)).toEqual([
            'mat-1',
            ...Array.from({ length: 10 }, (_, i) => `mat-${10 + i}`),
        ])
    })

    it.each(['endpoint', 'materialized'] as const)(
        'keeps the current endpoint version when the %s filter matches its history',
        async (filter) => {
            const versions = [1, 2].map((version) => ({
                ...buildView(`internal-query-${version}`, version === 1),
                origin: 'endpoint',
                endpoint: { name: 'weekly_activity', version, is_current: version === 2 },
            })) as DataWarehouseSavedQuery[]
            logic.actions.loadDataWarehouseSavedQueriesSuccess(versions)
            logic.actions.setTypeFilter(filter)
            logic.actions.setSearchTerm('weekly_activity')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filteredViews).toHaveLength(1)
            expect(logic.values.filteredViews[0].endpoint?.version).toBe(2)
            expect(logic.values.filteredViews[0].endpointVersions).toHaveLength(2)
        }
    )

    it('keeps expanded versions next to their parent when sorting and paginating', async () => {
        const versions = [1, 2].map((version) => ({
            ...buildView(`query-${version}`, false),
            created_at: `2024-0${version}-01T00:00:00Z`,
            origin: 'endpoint',
            endpoint: { name: 'weekly_activity', version, is_current: version === 2 },
        })) as DataWarehouseSavedQuery[]
        const otherViews = Array.from({ length: PAGE_SIZE }, (_, i) =>
            buildView(`view-${i}`, false)
        ) as DataWarehouseSavedQuery[]
        logic.actions.loadDataWarehouseSavedQueriesSuccess([...otherViews, ...versions])
        logic.actions.toggleEndpointExpanded('weekly_activity')
        logic.actions.setSorting({ columnKey: 'created_at', order: -1 })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.visibleViews).toHaveLength(PAGE_SIZE)
        expect(logic.values.visibleModelRows).toHaveLength(PAGE_SIZE + 2)
        expect(logic.values.visibleModelRows.slice(0, 3).map((view) => view.id)).toEqual([
            'query-2',
            'query-2',
            'query-1',
        ])
        logic.actions.setPage(2)
        expect(logic.values.visibleModelRows).toHaveLength(1)
    })

    it('keeps name matches visible while lineage data reloads', () => {
        lineageDataLogic.actions.loadNodes()
        logic.actions.setSearchTerm('+mat-1')

        expect(logic.values.filteredViews.map((view) => view.id)).toEqual([
            'mat-1',
            ...Array.from({ length: 10 }, (_, i) => `mat-${10 + i}`),
        ])
    })
    it('shows one success toast only after the confirmed deletion succeeds', async () => {
        const dialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        const toast = jest.spyOn(lemonToast, 'success').mockImplementation(() => '')
        try {
            logic.actions.deleteView('plain-a')
            const confirm = dialog.mock.calls[0][0].primaryButton!.onClick!
            confirm({} as React.MouseEvent<HTMLButtonElement>)
            expect(toast).not.toHaveBeenCalled()
            await expectLogic(dataWarehouseViewsLogic).toFinishAllListeners()
            expect(toast).toHaveBeenCalledTimes(1)
            expect(toast).toHaveBeenCalledWith('View deleted')
        } finally {
            dialog.mockRestore()
            toast.mockRestore()
        }
    })
})
