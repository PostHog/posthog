import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { QueryBasedInsightModel } from '~/types'

import { USER_INSIGHTS_HIGHLIGHT_THRESHOLD, addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'

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

    describe('without default-my-insights experiment', () => {
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

    describe('default-my-insights experiment created-by strategies', () => {
        const MOCK_USER_ID = MOCK_DEFAULT_USER.id

        // eslint-disable-next-line react-hooks/rules-of-hooks -- useMocks is not a React hook
        const setupMocksAndMount = (userInsightCount: number): void => {
            const userInsights = Array.from({ length: Math.min(userInsightCount, 5) }, (_, i) =>
                createInsight(100 + i, 'my-insight')
            )
            const allInsights = [
                ...userInsights,
                ...Array.from({ length: 10 }, (_, i) => createInsight(200 + i, 'other')),
            ]

            useMocks({
                get: {
                    '/api/environments/:team_id/insights/': (req) => {
                        const createdBy = req.url.searchParams.get('created_by')
                        const limit = parseInt(req.url.searchParams.get('limit') || '30', 10)

                        if (createdBy) {
                            return [200, { count: userInsightCount, results: userInsights.slice(0, limit) }]
                        }
                        return [200, { count: allInsights.length, results: allInsights.slice(0, limit) }]
                    },
                },
            })

            initKeaTests()
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_MODAL_DEFAULT_MY_INSIGHTS]: 'test',
            })
            userLogic.mount()
            userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)

            logic = addSavedInsightsModalLogic()
            logic.mount()
        }

        it('uses "none" strategy when user has no insights', async () => {
            setupMocksAndMount(0)

            await expectLogic(logic)
                .toDispatchActions(['initializeDefaultFilters', 'setCreatedByStrategy', 'loadInsights'])
                .toMatchValues({
                    createdByStrategy: 'none',
                })

            await expectLogic(logic)
                .toDispatchActions(['loadInsightsSuccess'])
                .toMatchValues({
                    filters: partial({ createdBy: 'All users' }),
                })
        })

        it('uses "highlight" strategy when user has few insights', async () => {
            const fewCount = USER_INSIGHTS_HIGHLIGHT_THRESHOLD - 1
            setupMocksAndMount(fewCount)

            await expectLogic(logic)
                .toDispatchActions([
                    'initializeDefaultFilters',
                    'setCreatedByStrategy',
                    'loadUserInsights',
                    'loadInsights',
                ])
                .toMatchValues({
                    createdByStrategy: 'highlight',
                })

            await expectLogic(logic)
                .toDispatchActions(['loadUserInsightsSuccess', 'loadInsightsSuccess'])
                .toMatchValues({
                    userInsights: expect.arrayContaining([partial({ name: 'my-insight 100' })]),
                    filters: partial({ createdBy: 'All users' }),
                })
        })

        it('uses "filter" strategy when user has many insights', async () => {
            setupMocksAndMount(USER_INSIGHTS_HIGHLIGHT_THRESHOLD + 10)
            const expectedCreatedBy = [MOCK_USER_ID]

            await expectLogic(logic)
                .toDispatchActions(['initializeDefaultFilters', 'setCreatedByStrategy', 'setModalFilters'])
                .toMatchValues({
                    createdByStrategy: 'filter',
                })

            await expectLogic(logic)
                .toDispatchActions(['loadInsightsSuccess'])
                .toMatchValues({
                    filters: partial({ createdBy: expectedCreatedBy }),
                })
        })
    })
})
