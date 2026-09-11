import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'

import { PAGE_SIZE, viewsTabLogic } from './viewsTabLogic'

function buildView(id: string, isMaterialized: boolean): Record<string, unknown> {
    return { id, name: id, columns: [], is_materialized: isMaterialized, created_at: '2024-01-01T00:00:00Z' }
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
                '/api/environments/:team_id/warehouse_saved_queries/': { count: views.length, results: views },
                '/api/environments/:team_id/data_modeling_nodes/': { count: 0, results: [] },
                '/api/environments/:team_id/data_modeling_edges/': { count: 0, results: [] },
                '/api/environments/:team_id/warehouse_saved_queries/:id/run_history/': (req) => {
                    runHistoryRequests.push(String(req.params.id))
                    return [200, { run_history: [] }]
                },
            },
            post: { '/api/environments/:team_id/query/': { tables: {} } },
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

        expect(logic.values.filteredViews.map((view) => view.id)).toEqual(['mat-1', 'mat-10'])
    })

    it('keeps name matches visible while lineage data reloads', () => {
        lineageDataLogic.actions.loadNodes()
        logic.actions.setSearchTerm('+mat-1')

        expect(logic.values.filteredViews.map((view) => view.id)).toEqual(['mat-1', 'mat-10'])
    })
})
