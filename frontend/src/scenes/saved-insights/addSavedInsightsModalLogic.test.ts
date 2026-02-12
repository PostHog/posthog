import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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

function enableExperiment(): void {
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_MODAL_SMART_DEFAULTS], {
        [FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_MODAL_SMART_DEFAULTS]: 'test',
    })
}

/** Mounts the logic, captures API URLs, and waits for the initial load to complete. */
function useSetupWithUrlCapture(options: { userInsightCount?: number; experiment?: boolean } = {}): {
    logic: ReturnType<typeof addSavedInsightsModalLogic.build>
    getCapturedUrl: () => URL | null
    getCapturedUrls: () => URL[]
} {
    const capturedUrls: URL[] = []
    const { userInsightCount = 0, experiment = false } = options

    useMocks({
        get: {
            '/api/environments/:team_id/insights/': (req) => {
                capturedUrls.push(req.url)
                if (req.url.searchParams.get('user') === 'true') {
                    return [200, { count: userInsightCount, results: [] }]
                }
                return [200, { count: 0, results: [] }]
            },
        },
    })
    initKeaTests()
    window.POSTHOG_APP_CONTEXT!.current_user = MOCK_DEFAULT_USER
    if (experiment) {
        enableExperiment()
    }
    const logic = addSavedInsightsModalLogic()
    logic.mount()

    return {
        logic,
        getCapturedUrl: () => (capturedUrls.length > 0 ? capturedUrls[capturedUrls.length - 1] : null),
        getCapturedUrls: () => capturedUrls,
    }
}

describe('addSavedInsightsModalLogic', () => {
    let logic: ReturnType<typeof addSavedInsightsModalLogic.build>

    describe('loadInsights filter params', () => {
        it('sends base params with defaults on mount', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()

            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            const url = getCapturedUrl()!
            expect(url.searchParams.get('order')).toBe('-last_modified_at')
            expect(url.searchParams.get('limit')).toBe('15')
            expect(url.searchParams.get('offset')).toBe('0')
            expect(url.searchParams.get('saved')).toBe('true')
            expect(url.searchParams.get('basic')).toBe('true')
            expect(url.searchParams.has('search')).toBe(false)
            expect(url.searchParams.has('insight')).toBe(false)
            expect(url.searchParams.has('created_by')).toBe(false)
            expect(url.searchParams.has('date_from')).toBe(false)
            expect(url.searchParams.has('date_to')).toBe(false)
        })

        it('includes search param when search is set', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            logic.actions.setModalFilters({ search: 'revenue' })
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            expect(getCapturedUrl()!.searchParams.get('search')).toBe('revenue')
        })

        it('uppercases insight type for the API', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            logic.actions.setModalFilters({ insightType: 'trends' })
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            expect(getCapturedUrl()!.searchParams.get('insight')).toBe('TRENDS')
        })

        it('excludes insight param when type is "All types"', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            expect(getCapturedUrl()!.searchParams.has('insight')).toBe(false)
        })

        it('includes created_by param when a specific user is set', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            logic.actions.setModalFilters({ createdBy: [42] })
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            expect(getCapturedUrl()!.searchParams.get('created_by')).toBe('[42]')
        })

        it('excludes created_by param when set to "All users"', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            expect(getCapturedUrl()!.searchParams.has('created_by')).toBe(false)
        })

        it('includes date_from and date_to when a date range is set', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            logic.actions.setModalFilters({ dateFrom: '2024-01-01', dateTo: '2024-06-01' })
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            const url = getCapturedUrl()!
            expect(url.searchParams.get('date_from')).toBe('2024-01-01')
            expect(url.searchParams.get('date_to')).toBe('2024-06-01')
        })

        it('excludes date params when dateFrom is "all"', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            const url = getCapturedUrl()!
            expect(url.searchParams.has('date_from')).toBe(false)
            expect(url.searchParams.has('date_to')).toBe(false)
        })

        it('includes dashboards param when dashboardId is set', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            logic.actions.setModalFilters({ dashboardId: 7 })
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            expect(getCapturedUrl()!.searchParams.get('dashboards')).toBe('[7]')
        })

        it('calculates offset from page number', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            logic.actions.setModalFilters({ page: 3 })
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            // page 3, 15 per page → offset 30
            expect(getCapturedUrl()!.searchParams.get('offset')).toBe('30')
        })
    })

    describe('smart defaults based on user insight count', () => {
        it('does not probe user insights without experiment flag', async () => {
            const { logic, getCapturedUrls } = useSetupWithUrlCapture({ userInsightCount: 5 })

            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            const userCalls = getCapturedUrls().filter((u) => u.searchParams.get('user') === 'true')
            expect(userCalls).toHaveLength(0)
            expect(logic.values.filters.createdBy).toBe('All users')
        })

        it('probes user insight count on mount with experiment flag', async () => {
            const { logic } = useSetupWithUrlCapture({ experiment: true })

            await expectLogic(logic).toDispatchActions([
                'loadUserInsights',
                'loadInsights',
                'loadUserInsightsSuccess',
                'loadInsightsSuccess',
            ])
        })

        it('0 user insights: no createdBy default', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture({ userInsightCount: 0, experiment: true })

            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            expect(logic.values.filters.createdBy).toBe('All users')
            expect(getCapturedUrl()!.searchParams.has('created_by')).toBe(false)
        })

        it('1+ user insights: defaults createdBy to current user', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture({ userInsightCount: 1, experiment: true })

            await expectLogic(logic).toDispatchActions(['loadUserInsightsSuccess', 'loadInsightsSuccess'])

            expect(logic.values.filters.createdBy).toEqual([MOCK_DEFAULT_USER.id])
            expect(getCapturedUrl()!.searchParams.get('created_by')).toBe(`[${MOCK_DEFAULT_USER.id}]`)
        })

        it('user can clear the createdBy default', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture({ userInsightCount: 5, experiment: true })

            await expectLogic(logic).toDispatchActions(['loadUserInsightsSuccess', 'loadInsightsSuccess'])

            logic.actions.setModalFilters({ createdBy: 'All users' })
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            expect(logic.values.filters.createdBy).toBe('All users')
            expect(getCapturedUrl()!.searchParams.has('created_by')).toBe(false)
        })
    })

    describe('debounce and cancellation', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/environments/:team_id/insights/': (req) => {
                        if (req.url.searchParams.get('user') === 'true') {
                            return [200, { count: 0, results: [] }]
                        }
                        const search = req.url.searchParams.get('search') ?? ''
                        const results = [createInsight(1, search || 'default'), createInsight(2, search || 'default')]
                        return [200, { count: results.length, results }]
                    },
                },
            })
            initKeaTests()
            window.POSTHOG_APP_CONTEXT!.current_user = MOCK_DEFAULT_USER
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
                        if (req.url.searchParams.get('user') === 'true') {
                            return [200, { count: 0, results: [] }]
                        }
                        const search = req.url.searchParams.get('search')
                        const label = search || 'unfiltered'
                        return [200, { count: 1, results: [createInsight(1, label)] }]
                    },
                },
            })

            logic = addSavedInsightsModalLogic()
            logic.mount()

            // afterMount dispatches loadInsights.
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
})
