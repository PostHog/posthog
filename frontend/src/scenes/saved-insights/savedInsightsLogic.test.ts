import { expectLogic, partial } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { InsightsResult, savedInsightsLogic } from './savedInsightsLogic'
import { DashboardItemType, InsightShortId, InsightType } from '~/types'
import { combineUrl, router } from 'kea-router'
import { defaultAPIMocks, MOCK_TEAM_ID, mockAPI } from 'lib/api.mock'
import { urls } from 'scenes/urls'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'

jest.mock('lib/api')

const Insight42 = 'ii42' as InsightShortId

const createInsight = (id: number, string = 'hi'): DashboardItemType =>
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
        tags: [],
        color: null,
        created_at: 'now',
        dashboard: null,
        deleted: false,
        saved: true,
        filters_hash: 'hash',
        filters: {},
    } as any as DashboardItemType)
const createSavedInsights = (string = 'hello'): InsightsResult => ({
    count: 3,
    results: [createInsight(1, string), createInsight(2, string), createInsight(3, string)],
})

describe('savedInsightsLogic', () => {
    let logic: ReturnType<typeof savedInsightsLogic.build>

    mockAPI(async (url) => {
        const {
            pathname,
            searchParams: { search },
        } = url
        if (pathname === `api/projects/${MOCK_TEAM_ID}/insights/`) {
            return createSavedInsights(search)
        }
        if (pathname === `api/projects/${MOCK_TEAM_ID}/insights/42`) {
            return createInsight(42)
        }
        if (pathname === `api/projects/${MOCK_TEAM_ID}/insights/123`) {
            return createInsight(123)
        }
        return defaultAPIMocks(url)
    })

    beforeEach(() => {
        initKeaTests()
        router.actions.push(urls.savedInsights())
        logic = savedInsightsLogic()
        logic.mount()
    })

    beforeEach(async () => {
        // wait for the initial load, and assure it fetches results after mount
        await expectLogic(logic).toDispatchActions(['setSavedInsightsFilters', 'loadInsights', 'loadInsightsSuccess'])
    })

    it('can filter the flags', async () => {
        // makes a search query
        logic.actions.setSavedInsightsFilters({ search: 'hello' })
        await expectLogic(logic)
            .toDispatchActions(['loadInsights', 'loadInsightsSuccess'])
            .toMatchValues({
                filters: partial({ search: 'hello' }),
                insights: {
                    results: partial([partial({ name: 'hello 1' })]),
                    count: 3,
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
                    filters: partial({ search: 'hello' }),
                },
            })
            .toDispatchActions(['loadInsightsSuccess'])
            .toMatchValues({
                filters: partial({ search: 'hello again' }),
                insights: {
                    results: partial([partial({ name: 'hello again 1' })]),
                    count: 3,
                    filters: partial({ search: 'hello again' }),
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
        it('in view mode with a #fromItem=', async () => {
            router.actions.push(
                combineUrl('/insights', cleanFilters({ insight: InsightType.TRENDS }), { fromItem: 42 }).url
            )
            await expectLogic(router)
                .delay(1)
                .toMatchValues({
                    location: partial({ pathname: urls.insightView(Insight42) }),
                    searchParams: partial({ insight: InsightType.TRENDS }),
                })
        })

        it('in edit mode with a #fromItem=', async () => {
            router.actions.push(
                combineUrl('/insights', cleanFilters({ insight: InsightType.TRENDS }), { fromItem: 42, edit: true }).url
            )
            await expectLogic(router)
                .delay(1)
                .toMatchValues({
                    location: partial({ pathname: urls.insightEdit(Insight42) }),
                    searchParams: partial({ insight: InsightType.TRENDS }),
                })
        })

        it('new mode with ?insight= and no hash params', async () => {
            router.actions.push(combineUrl('/insights', cleanFilters({ insight: InsightType.FUNNELS })).url)
            await expectLogic(router).toMatchValues({
                location: partial({ pathname: urls.insightNew() }),
                searchParams: partial({ insight: InsightType.FUNNELS }),
            })
        })
    })
})
