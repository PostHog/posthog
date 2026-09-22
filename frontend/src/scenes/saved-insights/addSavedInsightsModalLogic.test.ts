import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { ApiError, NetworkError } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { dashboardResult } from 'scenes/dashboard/dashboardLogic.testHelpers'
import { insightsApi } from 'scenes/insights/utils/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { QueryBasedInsightModel } from '~/types'

import { addSavedInsightsModalLogic, handleDashboardUpdateFailure } from './addSavedInsightsModalLogic'

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

function enableVariant(variant: 'filtered' | 'smart-filtered'): void {
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_MODAL_SMART_DEFAULTS], {
        [FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_MODAL_SMART_DEFAULTS]: variant,
    })
}

/** Mounts the logic, captures API URLs, and waits for the initial load to complete. */
function useSetupWithUrlCapture(options: { userInsightCount?: number; variant?: 'filtered' | 'smart-filtered' } = {}): {
    logic: ReturnType<typeof addSavedInsightsModalLogic.build>
    getCapturedUrl: () => URL | null
    getCapturedUrls: () => URL[]
} {
    const capturedUrls: URL[] = []
    const { userInsightCount = 0, variant } = options

    useMocks({
        get: {
            '/api/environments/:team_id/insights/': ({ request }) => {
                const url = new URL(request.url)
                capturedUrls.push(url)
                if (url.searchParams.get('user') === 'true') {
                    return [200, { count: userInsightCount, results: [] }]
                }
                return [200, { count: 0, results: [] }]
            },
        },
    })
    initKeaTests()
    window.POSTHOG_APP_CONTEXT!.current_user = MOCK_DEFAULT_USER
    if (variant) {
        enableVariant(variant)
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
            expect(url.searchParams.has('tags')).toBe(false)
        })

        it.each([
            ['search', { search: 'revenue' }, 'search', 'revenue'],
            ['insightType', { insightType: 'trends' }, 'insight', 'TRENDS'],
            ['createdBy', { createdBy: [42] }, 'created_by', '[42]'],
            ['tags', { tags: ['important', 'revenue'] }, 'tags', '["important","revenue"]'],
            ['dashboardId', { dashboardId: 7 }, 'dashboards', '[7]'],
            ['dateFrom', { dateFrom: '2024-01-01', dateTo: '2024-06-01' }, 'date_from', '2024-01-01'],
        ])('includes %s param in API call', async (_name, filterUpdate, expectedParam, expectedValue) => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture()
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            logic.actions.setModalFilters(filterUpdate as any)
            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            expect(getCapturedUrl()!.searchParams.get(expectedParam as string)).toBe(expectedValue)
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

    describe('smart defaults', () => {
        it('filtered variant enables UI but does not probe user insights', async () => {
            const { logic, getCapturedUrls } = useSetupWithUrlCapture({
                userInsightCount: 5,
                variant: 'filtered',
            })

            await expectLogic(logic).toDispatchActions(['loadInsightsSuccess'])

            const userCalls = getCapturedUrls().filter((u) => u.searchParams.get('user') === 'true')
            expect(userCalls).toHaveLength(0)
            expect(logic.values.filters.createdBy).toBe('All users')
            expect(logic.values.hasFilteredUI).toBe(true)
            expect(logic.values.hasSmartDefaults).toBe(false)
        })

        it('0 user insights: no createdBy default', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture({ userInsightCount: 0, variant: 'smart-filtered' })

            await expectLogic(logic).toDispatchActions([
                'loadUserInsights',
                'loadUserInsightsSuccess',
                'loadInsights',
                'loadInsightsSuccess',
            ])

            expect(logic.values.filters.createdBy).toBe('All users')
            expect(getCapturedUrl()!.searchParams.has('created_by')).toBe(false)
        })

        it('1+ user insights: defaults createdBy to current user', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture({ userInsightCount: 1, variant: 'smart-filtered' })

            await expectLogic(logic).toDispatchActions(['loadUserInsightsSuccess', 'loadInsightsSuccess'])

            expect(logic.values.filters.createdBy).toEqual([MOCK_DEFAULT_USER.id])
            expect(getCapturedUrl()!.searchParams.get('created_by')).toBe(`[${MOCK_DEFAULT_USER.id}]`)
        })

        it('user can clear the createdBy default', async () => {
            const { logic, getCapturedUrl } = useSetupWithUrlCapture({ userInsightCount: 5, variant: 'smart-filtered' })

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
                    '/api/environments/:team_id/insights/': ({ request }) => {
                        const url = new URL(request.url)
                        if (url.searchParams.get('user') === 'true') {
                            return [200, { count: 0, results: [] }]
                        }
                        const search = url.searchParams.get('search') ?? ''
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
                    '/api/environments/:team_id/insights/': ({ request }) => {
                        const url = new URL(request.url)
                        if (url.searchParams.get('user') === 'true') {
                            return [200, { count: 0, results: [] }]
                        }
                        const search = url.searchParams.get('search')
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

    describe('dashboard membership updates', () => {
        const MESSAGES = { timedOut: 'Timed out', failed: 'Failed to add' }

        const insightOnDashboards = (dashboardIds: number[]): QueryBasedInsightModel =>
            ({
                ...createInsight(53),
                dashboard_tiles: dashboardIds.map((dashboardId, index) => ({
                    id: index + 1,
                    dashboard_id: dashboardId,
                    deleted: false,
                })),
            }) as QueryBasedInsightModel

        it('keeps the other dashboards when adding', async () => {
            initKeaTests()
            const update = jest.spyOn(insightsApi, 'update').mockResolvedValue(createInsight(53))
            const logic = addSavedInsightsModalLogic()
            logic.mount()

            await expectLogic(logic, () =>
                logic.actions.addInsightToDashboard(insightOnDashboards([7, 8]), 9)
            ).toFinishAllListeners()

            expect(update).toHaveBeenCalledWith(53, { dashboards: [7, 8, 9] })

            logic.unmount()
        })

        it('keeps the other dashboards when removing', async () => {
            initKeaTests()
            const update = jest.spyOn(insightsApi, 'update').mockResolvedValue(createInsight(53))
            const logic = addSavedInsightsModalLogic()
            logic.mount()

            await expectLogic(logic, () =>
                logic.actions.removeInsightFromDashboard(insightOnDashboards([7, 8]), 8)
            ).toFinishAllListeners()

            expect(update).toHaveBeenCalledWith(53, { dashboards: [7] })

            logic.unmount()
        })

        it.each([
            [500, null],
            [403, "You don't have permission to remove insights from dashboard: 7"],
        ])('handles a %s instead of filing an unhandled rejection', async (status, detail) => {
            initKeaTests()
            const toastError = jest.spyOn(lemonToast, 'error').mockImplementation()
            jest.spyOn(insightsApi, 'update').mockRejectedValue(
                new ApiError('Non-OK response', status, undefined, { detail })
            )
            const logic = addSavedInsightsModalLogic()
            logic.mount()

            await expect(
                expectLogic(logic, () =>
                    logic.actions.addInsightToDashboard(insightOnDashboards([7]), 9)
                ).toFinishAllListeners()
            ).resolves.toBeDefined()

            expect(toastError).toHaveBeenCalledWith(detail ?? 'Failed to add insight to dashboard')

            logic.unmount()
        })

        it.each([
            ['a 500 the backend answered with', () => new ApiError('Non-OK response', 500), 'Failed to add'],
            ['a request the browser dropped', () => new NetworkError('network'), 'Failed to add'],
        ])('consumes %s', (_label, buildError, expectedToast) => {
            const toastError = jest.spyOn(lemonToast, 'error').mockImplementation()

            expect(() => handleDashboardUpdateFailure(buildError(), MESSAGES)).not.toThrow()

            expect(toastError).toHaveBeenCalledWith(expectedToast)
        })

        it.each([
            ['the fetcher threw before a response arrived', () => new ApiError('the fetcher itself broke')],
            [
                'a 2xx body would not parse',
                () => new ApiError('Malformed JSON response [PATCH /api/environments/2/insights/53/] (status 200)'),
            ],
        ])('rethrows a status-less failure, because %s and nothing else records it', (_label, buildError) => {
            const toastError = jest.spyOn(lemonToast, 'error').mockImplementation()
            const error = buildError()

            expect(() => handleDashboardUpdateFailure(error, MESSAGES)).toThrow(error)

            // The user sees the same sentence either way: the rethrow only restores the signal.
            expect(toastError).toHaveBeenCalledWith('Failed to add')
        })
    })

    it('refreshes the mounted dashboard after adding an insight', async () => {
        initKeaTests()
        const dashboard = dashboardLogic({ id: 1, dashboard: dashboardResult(1, []) })
        dashboard.mount()
        const loadDashboard = jest.spyOn(dashboard.actions, 'loadDashboard').mockImplementation()
        jest.spyOn(insightsApi, 'update').mockResolvedValue(createInsight(1))

        const logic = addSavedInsightsModalLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.addInsightToDashboard(createInsight(1), 1)).toFinishAllListeners()

        expect(loadDashboard).toHaveBeenCalledWith({ action: DashboardLoadAction.Update })

        logic.unmount()
        dashboard.unmount()
    })
})
