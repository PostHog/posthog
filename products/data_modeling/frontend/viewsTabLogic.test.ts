import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import * as accessControlUtils from 'lib/utils/accessControlUtils'
import type { DataWarehouseSavedQuerySummary } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { dataWarehouseViewsLogic } from 'scenes/data-warehouse/saved_queries/dataWarehouseViewsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'
import * as endpointsApi from 'products/endpoints/frontend/generated/api'
import type { EndpointResponseApi, EndpointVersionResponseApi } from 'products/endpoints/frontend/generated/api.schemas'

import { PAGE_SIZE, viewsTabLogic } from './viewsTabLogic'

function buildView(id: string, isMaterialized: boolean, status?: string): DataWarehouseSavedQuerySummary {
    return {
        id,
        name: id,
        managed_viewset_kind: null,
        latest_error: null,
        is_materialized: isMaterialized,
        status,
        created_at: '2024-01-01T00:00:00Z',
    }
}

describe('viewsTabLogic', () => {
    let logic: ReturnType<typeof viewsTabLogic.build>
    let runHistoryRequests: string[]

    beforeEach(async () => {
        runHistoryRequests = []
        const views = [
            ...Array.from({ length: PAGE_SIZE + 1 }, (_, i) =>
                buildView(`mat-${i}`, true, i === 1 ? 'Running' : i === 10 ? 'Failed' : 'Completed')
            ),
            buildView('plain-a', false),
            buildView('plain-b', false),
        ]
        useMocks({
            get: {
                '/api/projects/:team_id/endpoints/': { count: 0, results: [] },
                '/api/projects/:team_id/endpoints/:name/versions/': { count: 0, results: [] },
                '/api/projects/:team_id/warehouse_saved_queries/': { count: views.length, results: views },
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
        jest.spyOn(accessControlUtils, 'userHasAccess').mockReturnValue(true)
        logic = viewsTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
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

    it('search, status, and type filters compose', async () => {
        logic.actions.setTypeFilter('materialized')
        logic.actions.setSearchTerm('mat-1 status:failed')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filteredViews.map((view) => view.id)).toEqual(['mat-10'])
    })

    it.each([
        ['a materialize', 'plain-a', true],
        ['an unmaterialize', 'mat-0', false],
    ])('shows the new materialization after %s suggestion is accepted', async (_kind, viewId, isMaterialized) => {
        useMocks({
            get: {
                '/api/projects/:team_id/warehouse_saved_queries/': {
                    count: 1,
                    results: [buildView(viewId, isMaterialized, isMaterialized ? 'Completed' : undefined)],
                },
            },
        })

        logic.actions.suggestionAccepted(viewId, isMaterialized)
        await expectLogic(dataWarehouseViewsLogic).toFinishAllListeners()
        logic.actions.setTypeFilter(isMaterialized ? 'materialized' : 'view')

        expect(logic.values.filteredViews.map((view) => view.id)).toEqual([viewId])
    })

    it.each([
        ['a materialize', 'view' as const, false],
        ['an unmaterialize', 'materialized' as const, true],
    ])(
        'moves back to the last page when %s empties the filtered page',
        async (_kind, typeFilter, startsMaterialized) => {
            const views = Array.from({ length: PAGE_SIZE + 1 }, (_, i) => buildView(`v-${i}`, startsMaterialized))
            useMocks({
                get: { '/api/projects/:team_id/warehouse_saved_queries/': { count: views.length, results: views } },
            })
            dataWarehouseViewsLogic.actions.loadDataWarehouseSavedQueries()
            await expectLogic(dataWarehouseViewsLogic).toFinishAllListeners()
            logic.actions.setTypeFilter(typeFilter)
            logic.actions.setPage(2)
            const flipped = views.map((view, i) => (i === PAGE_SIZE ? buildView(`v-${i}`, !startsMaterialized) : view))
            useMocks({
                get: {
                    '/api/projects/:team_id/warehouse_saved_queries/': { count: flipped.length, results: flipped },
                },
            })

            logic.actions.suggestionAccepted(`v-${PAGE_SIZE}`, !startsMaterialized)
            await expectLogic(dataWarehouseViewsLogic).toFinishAllListeners()

            expect(logic.values.currentPage).toEqual(1)
            expect(logic.values.visibleViews).toHaveLength(PAGE_SIZE)
        }
    )

    it('keeps polling an accepted materialize until the view reports it is materialized', async () => {
        logic.actions.suggestionAccepted('plain-a', true)
        await expectLogic(dataWarehouseViewsLogic).toFinishAllListeners()

        expect(dataWarehouseViewsLogic.values.materializingViewIds).toEqual(['plain-a'])
    })

    it.each(['endpoint', 'materialized'] as const)(
        'keeps the current endpoint version when the %s filter matches its history',
        async (filter) => {
            const versions = [1, 2].map((version) => ({
                ...buildView(`internal-query-${version}`, version === 1),
                origin: 'endpoint',
                endpoint: { name: 'weekly_activity', version, is_current: version === 2 },
            })) as DataWarehouseSavedQuerySummary[]
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
        })) as DataWarehouseSavedQuerySummary[]
        const otherViews = Array.from({ length: PAGE_SIZE }, (_, i) =>
            buildView(`view-${i}`, false)
        ) as DataWarehouseSavedQuerySummary[]
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
    it.each(['success', 'failure'])('ignores a late endpoint page %s after a project change', async (outcome) => {
        let resolveOld!: (response: Awaited<ReturnType<typeof endpointsApi.endpointsList>>) => void
        let rejectOld!: (error: Error) => void
        const oldTeamId = String(teamLogic.values.currentTeamId)
        const pending = new Promise<Awaited<ReturnType<typeof endpointsApi.endpointsList>>>((resolve, reject) => {
            resolveOld = resolve
            rejectOld = reject
        })
        const current = { id: 'new-project-endpoint', name: 'weekly_activity' } as EndpointResponseApi
        const request = jest
            .spyOn(endpointsApi, 'endpointsList')
            .mockImplementation((teamId) =>
                teamId === oldTeamId
                    ? pending
                    : Promise.resolve({ results: [current], count: 1, next: null, previous: null })
            )
        const oldRequest = logic.asyncActions.loadModelEndpoints()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 1234 })
        await logic.asyncActions.loadModelEndpoints()
        expect(logic.values.modelEndpointVersions).toEqual({})
        if (outcome === 'success') {
            resolveOld({
                results: [{ id: 'old-project-endpoint' } as EndpointResponseApi],
                count: 2,
                next: 'next-page',
                previous: null,
            })
        } else {
            rejectOld(new Error('Old project request failed'))
        }
        await oldRequest
        expect(logic.values.modelEndpoints).toEqual([current])
        expect(logic.values.endpointsError).toBe(false)
        expect(request.mock.calls.filter(([teamId]) => teamId === oldTeamId)).toHaveLength(1)
    })

    it('clears cached versions and ignores a late version response after a project change', async () => {
        const cached = { version: 1 } as EndpointVersionResponseApi
        logic.actions.loadModelEndpointVersionsSuccess({ weekly_activity: [cached] })
        logic.actions.toggleEndpointExpanded('weekly_activity')
        let resolveOld!: (response: Awaited<ReturnType<typeof endpointsApi.endpointsVersionsList>>) => void
        const pending = new Promise<Awaited<ReturnType<typeof endpointsApi.endpointsVersionsList>>>((resolve) => {
            resolveOld = resolve
        })
        jest.spyOn(endpointsApi, 'endpointsVersionsList').mockReturnValue(pending)
        const oldRequest = logic.asyncActions.loadModelEndpointVersions('other_endpoint')
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 1234 })
        expect(logic.values.modelEndpointVersions).toEqual({})
        expect(logic.values.expandedEndpointNames).toEqual([])
        resolveOld({ results: [cached], count: 1, next: null, previous: null })
        await oldRequest
        expect(logic.values.modelEndpointVersions).toEqual({})
    })

    it('keeps the model list usable when endpoint access is denied', async () => {
        jest.mocked(accessControlUtils.userHasAccess).mockReturnValue(false)
        const request = jest.spyOn(endpointsApi, 'endpointsList')
        await logic.asyncActions.loadModelEndpoints()
        expect(request).not.toHaveBeenCalled()
        expect(logic.values.modelEndpoints).toEqual([])
        expect(logic.values.endpointsError).toBe(false)
    })
})
