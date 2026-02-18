import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { QueryBasedInsightModel } from '~/types'

import { addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'

const createInsight = (id: number, name = 'test'): QueryBasedInsightModel =>
    ({
        id,
        name: `${name} ${id}`,
        short_id: `ii${id}`,
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
        query: {},
    }) as any as QueryBasedInsightModel

describe('addSavedInsightsModalLogic', () => {
    let logic: ReturnType<typeof addSavedInsightsModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/': (req) => {
                    const search = req.url.searchParams.get('search') ?? ''
                    const results = [createInsight(1, search || 'default'), createInsight(2, search || 'default')]
                    return [200, { count: results.length, results }]
                },
            },
        })
        initKeaTests()
        logic = addSavedInsightsModalLogic()
        logic.mount()
    })

    beforeEach(async () => {
        await expectLogic(logic).toDispatchActions(['loadInsights', 'loadInsightsSuccess'])
    })

    it('search filter cancels in-flight unfiltered request', async () => {
        logic.unmount()

        useMocks({
            get: {
                '/api/environments/:team_id/insights/': (req) => {
                    const search = req.url.searchParams.get('search')
                    const label = search || 'unfiltered'
                    return [200, { count: 1, results: [createInsight(1, label)] }]
                },
            },
        })

        logic = addSavedInsightsModalLogic()
        logic.mount()

        // afterMount dispatches loadInsights which debounces.
        // Setting a filter dispatches another loadInsights, cancelling the first via breakpoint.
        logic.actions.setModalFilters({ search: 'my query' })

        await expectLogic(logic)
            .toDispatchActions(['loadInsightsSuccess'])
            .toMatchValues({
                filters: partial({ search: 'my query' }),
                insights: partial({ results: [partial({ name: 'my query 1' })] }),
            })
    })

    it('rapid filter changes only produce one API call due to debounce', async () => {
        let apiCallCount = 0

        useMocks({
            get: {
                '/api/environments/:team_id/insights/': () => {
                    apiCallCount++
                    return [200, { count: 1, results: [createInsight(1, 'abc')] }]
                },
            },
        })

        apiCallCount = 0

        logic.actions.setModalFilters({ search: 'a' })
        logic.actions.setModalFilters({ search: 'ab' })
        logic.actions.setModalFilters({ search: 'abc' })

        await expectLogic(logic)
            .toDispatchActions(['loadInsightsSuccess'])
            .toMatchValues({
                filters: partial({ search: 'abc' }),
            })

        expect(apiCallCount).toBe(1)
    })
})
