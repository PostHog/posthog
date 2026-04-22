import { expectLogic } from 'kea-test-utils'

import { quickFiltersSectionLogic } from 'lib/components/QuickFilters'
import { quickFiltersLogic } from 'lib/components/QuickFilters/quickFiltersLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { QuickFilterContext } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightShortId, PropertyOperator, QueryBasedInsightModel, QuickFilterOption } from '~/types'

import { dashboardResult, insightOnDashboard, tileFromInsight } from './dashboardLogic.test'
import { QUICK_FILTER_DEBOUNCE_MS } from './dashboardUtils'

const mockOption: QuickFilterOption = {
    id: 'opt-1',
    value: 'production',
    label: 'Production',
    operator: PropertyOperator.Exact,
}

const mockQuickFilters = [
    {
        id: 'filter-1',
        name: 'Environment',
        property_name: '$environment',
        type: 'manual-options',
        options: [mockOption],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
    {
        id: 'filter-2',
        name: 'Browser',
        property_name: '$browser',
        type: 'manual-options',
        options: [{ id: 'opt-chrome', value: 'Chrome', label: 'Chrome', operator: PropertyOperator.Exact }],
        contexts: [QuickFilterContext.Dashboards],
        created_at: '2024-01-01',
        updated_at: '2024-01-01',
    },
]

const makeInsight = (id: number): QueryBasedInsightModel => ({
    ...insightOnDashboard(id, [1]),
    id,
    short_id: `${id}` as InsightShortId,
    last_refresh: new Date().toISOString(),
})

const insight1 = makeInsight(101)
const insight2 = makeInsight(102)

function setupDashboard(quickFilterIds: string[] | null): () => {
    logic: ReturnType<typeof dashboardLogic.build>
    sectionLogic: ReturnType<typeof quickFiltersSectionLogic.build>
} {
    let logic: ReturnType<typeof dashboardLogic.build>
    let sectionLogic: ReturnType<typeof quickFiltersSectionLogic.build>

    beforeEach(async () => {
        const dashboard = {
            ...dashboardResult(1, [tileFromInsight(insight1), tileFromInsight(insight2)]),
            quick_filter_ids: quickFilterIds,
        }

        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/1/': dashboard,
                '/api/environments/:team_id/dashboards/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [dashboard],
                },
                '/api/environments/:team_id/insights/:id/': (req) => {
                    const id =
                        typeof req.params['id'] === 'string'
                            ? parseInt(req.params['id'])
                            : parseInt(req.params['id'][0])
                    if (id === 101) {
                        return [200, insight1]
                    }
                    if (id === 102) {
                        return [200, insight2]
                    }
                    return [404, null]
                },
                '/api/environments/:team_id/quick_filters/': { results: mockQuickFilters },
            },
            post: {
                '/api/environments/:team_id/insights/cancel/': [201],
            },
        })

        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DASHBOARD_QUICK_FILTERS_EXPERIMENT], {
            [FEATURE_FLAGS.DASHBOARD_QUICK_FILTERS_EXPERIMENT]: 'test',
        })
        dashboardsModel.mount()
        insightsModel.mount()

        const filtersLogic = quickFiltersLogic({ context: QuickFilterContext.Dashboards })
        filtersLogic.mount()
        await expectLogic(filtersLogic).toDispatchActions(['loadQuickFiltersSuccess'])

        sectionLogic = quickFiltersSectionLogic({ context: QuickFilterContext.Dashboards })
        sectionLogic.mount()

        logic = dashboardLogic({ id: 1 })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDashboardSuccess'])
    })

    return () => ({ logic, sectionLogic })
}

describe('dashboard quick filters debounce', () => {
    describe.each([
        ['single visible filter', ['filter-1']],
        ['no quick_filter_ids', null],
    ] as const)('%s', (_label, quickFilterIds) => {
        const getLogics = setupDashboard(quickFilterIds as string[] | null)

        it('refreshes immediately', async () => {
            const { logic, sectionLogic } = getLogics()

            await expectLogic(logic, () => {
                sectionLogic.actions.setQuickFilterValue('filter-1', '$environment', mockOption)
            }).toDispatchActions(['refreshDashboardItems'])
        })
    })

    describe('multiple visible filters', () => {
        const getLogics = setupDashboard(['filter-1', 'filter-2'])

        it('debounces and sets tiles as queued', async () => {
            const { logic, sectionLogic } = getLogics()

            jest.useFakeTimers()

            sectionLogic.actions.setQuickFilterValue('filter-1', '$environment', mockOption)

            // Tiles should be queued immediately
            await expectLogic(logic)
                .toDispatchActions(['setRefreshStatuses'])
                .toMatchValues({
                    refreshStatus: expect.objectContaining({
                        '101': expect.objectContaining({ queued: true }),
                        '102': expect.objectContaining({ queued: true }),
                    }),
                })

            // Should NOT have refreshed yet
            await expectLogic(logic).toNotHaveDispatchedActions(['refreshDashboardItems'])

            await jest.advanceTimersByTimeAsync(QUICK_FILTER_DEBOUNCE_MS)

            await expectLogic(logic).toDispatchActions(['refreshDashboardItems'])

            jest.useRealTimers()
        })
    })
})
