import { expectLogic, partial } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { InsightsResult, savedInsightsLogic } from './savedInsightsLogic'
import { DashboardItemType } from '~/types'
import { combineUrl, router } from 'kea-router'

const createInsight = (obj: Partial<DashboardItemType> = {}, string = 'hi'): DashboardItemType => ({
    id: 1,
    name: `${string} ${obj.id || 1}`,
    short_id: 'insght',
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
    ...obj,
})
const createSavedInsights = (string = 'hello'): InsightsResult => ({
    count: 3,
    results: [createInsight({ id: 1 }, string), createInsight({ id: 2 }, string), createInsight({ id: 3 }, string)],
})

global.fetch = jest.fn((url: any) => {
    const {
        searchParams: { search },
    } = combineUrl(url)
    return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(createSavedInsights(search)),
    } as any as Response)
})

describe('saved insight logic', () => {
    let logic: ReturnType<typeof savedInsightsLogic.build>
    initKeaTestLogic()

    beforeEach(() => {
        router.actions.push('/saved_insights')
        logic = savedInsightsLogic()
        logic.mount()
    })

    it('loads results on mount', async () => {
        await expectLogic(logic).toDispatchActions(['setSavedInsightsFilters', 'loadInsights', 'loadInsightsSuccess'])
    })

    describe('after mount', () => {
        beforeEach(async () => {
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])
        })

        it('can filter the flags', async () => {
            logic.actions.setSavedInsightsFilters({ search: 'hello' })
            await expectLogic(logic)
                .toDispatchActions(['loadInsights', 'loadInsightsSuccess'])
                .toMatchValues({
                    filters: partial({ search: 'hello' }),
                    insights: { results: partial([partial({ name: 'hello 1' })]), count: 3 },
                })

            logic.actions.setSavedInsightsFilters({ search: 'hello' })
            await expectLogic(logic)
                .toNotHaveDispatchedActions(['loadInsights', 'loadInsightsSuccess'])
                .toMatchValues({
                    filters: partial({ search: 'hello' }),
                    insights: { results: partial([partial({ name: 'hello 1' })]), count: 3 },
                })

            logic.actions.setSavedInsightsFilters({ search: 'hello again' })
            await expectLogic(logic)
                .toDispatchActions(['loadInsights', 'loadInsightsSuccess'])
                .toMatchValues({
                    filters: partial({ search: 'hello again' }),
                    insights: { results: partial([partial({ name: 'hello again 1' })]), count: 3 },
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
    })
})
