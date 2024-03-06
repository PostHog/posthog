import { combineUrl, router } from 'kea-router'
import { expectLogic, partial } from 'kea-test-utils'
import api from 'lib/api'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { DeleteDashboardForm, deleteDashboardLogic } from 'scenes/dashboard/deleteDashboardLogic'
import { DuplicateDashboardForm, duplicateDashboardLogic } from 'scenes/dashboard/duplicateDashboardLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { initKeaTests } from '~/test/init'
import { InsightModel, InsightType } from '~/types'

import { InsightsResult, savedInsightsLogic } from './savedInsightsLogic'

jest.spyOn(api, 'create')

const createInsight = (id: number, string = 'hi'): InsightModel =>
    ({
        id: id || 1,
        name: `${string} ${id || 1}`,
        short_id: `ii${id || 1}`,
        order: 0,
        layouts: [],
        last_refresh: 'now',
        refreshing: false,
        created_by: null,
        is_sample: false,
        updated_at: 'now',
        result: {},
        color: null,
        created_at: 'now',
        dashboard: null,
        deleted: false,
        saved: true,
        filters: {},
    } as any as InsightModel)
const createSavedInsights = (string = 'hello', offset: number): InsightsResult => ({
    count: 3,
    results: [createInsight(1, string), createInsight(2, string), createInsight(3, string)].slice(offset),
    offset: 0,
})

describe('savedInsightsLogic', () => {
    let logic: ReturnType<typeof savedInsightsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/insights/': (req) => [
                    200,
                    createSavedInsights(
                        req.url.searchParams.get('search') ?? '',
                        parseInt(req.url.searchParams.get('offset') ?? '0')
                    ),
                ],
                '/api/projects/:team/insights/42': createInsight(42),
                '/api/projects/:team/insights/123': createInsight(123),
            },
            post: {
                '/api/projects/:team/insights/': () => [200, createInsight(42)],
            },
        })
        initKeaTests()
        router.actions.push(urls.savedInsights())
        logic = savedInsightsLogic()
        logic.mount()
    })

    beforeEach(async () => {
        // wait for the initial load, and assure it fetches results after mount
        await expectLogic(logic).toDispatchActions(['setSavedInsightsFilters', 'loadInsights', 'loadInsightsSuccess'])
    })

    it('can filter the insights', async () => {
        // makes a search query
        logic.actions.setSavedInsightsFilters({ search: 'hello' })
        await expectLogic(logic)
            .toDispatchActions(['loadInsights', 'loadInsightsSuccess'])
            .toMatchValues({
                filters: partial({ search: 'hello' }),
                insights: {
                    results: partial([partial({ name: 'hello 1' })]),
                    count: 3,
                    offset: 0,
                    filters: partial({ search: 'hello' }),
                },
            })

        // will not search for a second time
        logic.actions.setSavedInsightsFilters({ search: 'hello' })
        await expectLogic(logic)
            .toNotHaveDispatchedActions(['loadInsights', 'loadInsightsSuccess'])
            .toMatchValues({
                filters: partial({ search: 'hello' }),
                insights: {
                    results: partial([partial({ name: 'hello 1' })]),
                    count: 3,
                    offset: 0,
                    filters: partial({ search: 'hello' }),
                },
            })

        // insights.filters always has the loaded filters
        logic.actions.setSavedInsightsFilters({ search: 'hello again' })
        await expectLogic(logic)
            .toDispatchActions(['loadInsights'])
            .toMatchValues({
                filters: partial({ search: 'hello again' }),
                insights: {
                    results: partial([partial({ name: 'hello 1' })]),
                    count: 3,
                    offset: 0,
                    filters: partial({ search: 'hello' }),
                },
            })
            .toDispatchActions(['loadInsightsSuccess'])
            .toMatchValues({
                filters: partial({ search: 'hello again' }),
                insights: {
                    results: partial([partial({ name: 'hello again 1' })]),
                    count: 3,
                    offset: 0,
                    filters: partial({ search: 'hello again' }),
                },
            })
    })

    it('resets the page on filter change', async () => {
        logic.actions.setSavedInsightsFilters({ page: 2 })
        await expectLogic(logic)
            .toDispatchActions(['loadInsights', 'loadInsightsSuccess'])
            .toMatchValues({
                filters: partial({ page: 2, search: '' }),
                insights: {
                    results: [],
                    count: 3,
                    offset: 30,
                    filters: partial({ page: 2, search: '' }),
                },
            })

        logic.actions.setSavedInsightsFilters({ search: 'hello' })
        await expectLogic(logic)
            .toDispatchActions(['loadInsights', 'loadInsightsSuccess'])
            .toMatchValues({
                filters: partial({ page: 1, search: 'hello' }),
                insights: {
                    results: partial([partial({ name: 'hello 1' })]),
                    count: 3,
                    offset: 0,
                    filters: partial({ page: 1, search: 'hello' }),
                },
            })
    })

    it('persists the filter in the url', async () => {
        logic.actions.setSavedInsightsFilters({ search: 'hello' })
        await expectLogic(logic)
            .toDispatchActions(['loadInsightsSuccess'])
            .toMatchValues({ filters: partial({ search: 'hello' }) })
            .toMatchValues(router, { searchParams: { search: 'hello' } })

        router.actions.push(router.values.location.pathname, { search: 'hoi' })
        await expectLogic(logic)
            .toDispatchActions(['loadInsightsSuccess'])
            .toMatchValues({ filters: partial({ search: 'hoi' }) })
            .toMatchValues(router, { searchParams: { search: 'hoi' } })
    })

    it('makes a direct ID query if searching for a number', async () => {
        logic.actions.setSavedInsightsFilters({ search: '123' })
        await expectLogic(logic)
            .toDispatchActions(['loadInsightsSuccess'])
            .toMatchValues({
                insights: partial({
                    filters: partial({ search: '123' }),
                    results: [partial({ id: 123 }), partial({ id: 1 }), partial({ id: 2 }), partial({ id: 3 })],
                }),
            })
    })

    describe('redirects old /insights urls to the real URL', () => {
        it('new mode with ?insight= and no hash params', async () => {
            router.actions.push(combineUrl('/insights', cleanFilters({ insight: InsightType.FUNNELS })).url)
            await expectLogic(router).toMatchValues({
                location: partial({ pathname: urls.insightNew() }),
                hashParams: { filters: partial({ insight: InsightType.FUNNELS }) },
            })
        })
    })

    it('can duplicate and does not use derived name for name', async () => {
        const sourceInsight = createInsight(123, 'hello')
        sourceInsight.name = ''
        sourceInsight.derived_name = 'should be copied'
        await logic.asyncActions.duplicateInsight(sourceInsight)
        expect(api.create).toHaveBeenCalledWith(
            `api/projects/${MOCK_TEAM_ID}/insights`,
            expect.objectContaining({ name: '' })
        )
    })

    it('can duplicate using name', async () => {
        const sourceInsight = createInsight(123, 'hello')
        sourceInsight.name = 'should be copied'
        sourceInsight.derived_name = ''
        await logic.asyncActions.duplicateInsight(sourceInsight)
        expect(api.create).toHaveBeenCalledWith(
            `api/projects/${MOCK_TEAM_ID}/insights`,
            expect.objectContaining({ name: 'should be copied (copy)' })
        )
    })

    describe('reacts to external updates', () => {
        it('loads insights when a dashboard is duplicated', async () => {
            await expectLogic(logic, () => {
                duplicateDashboardLogic.actions.submitDuplicateDashboardSuccess({
                    duplicateTiles: true,
                } as DuplicateDashboardForm)
            }).toDispatchActions(['loadInsights'])
        })

        it('loads insights when a dashboard is deleted', async () => {
            await expectLogic(logic, () => {
                deleteDashboardLogic.actions.submitDeleteDashboardSuccess({
                    deleteInsights: true,
                } as DeleteDashboardForm)
            }).toDispatchActions(['loadInsights'])
        })

        it('updates the list when an insight is changed', async () => {
            await expectLogic(logic, () => {
                dashboardsModel.actions.updateDashboardInsight(createInsight(1, 'a new name'))
            }).toDispatchActions(['setInsight'])
        })

        it('adds to the list when a new insight is reported as changed', async () => {
            await expectLogic(logic, () => {
                dashboardsModel.actions.updateDashboardInsight(createInsight(100, 'a new insight'))
            }).toDispatchActions(['addInsight'])
        })
    })
})
