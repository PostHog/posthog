import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dashboardLogic, RefreshDashboardItemsAction } from 'scenes/dashboard/dashboardLogic'
import * as dashboardUtils from 'scenes/dashboard/dashboardUtils'
import { dashboardV2Logic } from 'scenes/dashboard/dashboardV2Logic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightShortId } from '~/types'

import { dashboardResult, insightOnDashboard, tileFromInsight } from './dashboardLogic.testHelpers'

describe('dashboardV2Logic', () => {
    let logic: ReturnType<typeof dashboardLogic.build>
    let refreshInsight: jest.SpiedFunction<typeof dashboardUtils.getInsightWithRetry>
    const tiles = Array.from({ length: 15 }, (_, index) =>
        tileFromInsight(
            {
                ...insightOnDashboard(175, [21]),
                id: 900 + index,
                short_id: `long-${index}` as InsightShortId,
                cache_target_age: undefined,
            },
            9000 + index
        )
    )
    const v2Logic = (): ReturnType<typeof dashboardV2Logic.build> => dashboardV2Logic({ id: 21 })
    const loadedShortIds = (): string[] => refreshInsight.mock.calls.map((call) => call[1].short_id)
    const setDashboardV2 = (enabled: boolean): void => {
        const flags = enabled ? [FEATURE_FLAGS.DASHBOARD_V2, FEATURE_FLAGS.DASHBOARD_V2_USERS] : []
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    }
    const autoRefresh = async (): Promise<void> => {
        await expectLogic(logic, () => {
            logic.actions.refreshDashboardItems({
                action: RefreshDashboardItemsAction.Refresh,
                forceRefresh: true,
                isAutomatic: true,
            })
        }).toFinishAllListeners()
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/dashboards/21/': () => [200, dashboardResult(21, tiles)],
            },
            post: {
                '/api/environments/:team_id/insights/cancel/': [201],
            },
        })
        initKeaTests()
        dashboardsModel.mount()
        insightsModel.mount()
        refreshInsight = jest
            .spyOn(dashboardUtils, 'getInsightWithRetry')
            .mockImplementation((_teamId, insight) => Promise.resolve(insight))
    })

    afterEach(() => {
        refreshInsight.mockRestore()
        setDashboardV2(false)
    })

    it('queries the first screen up front and each later tile once it scrolls into view', async () => {
        setDashboardV2(true)
        logic = dashboardLogic({ id: 21 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(loadedShortIds()).toEqual(tiles.slice(0, 12).map((tile) => tile.insight!.short_id))

        await expectLogic(logic, () => {
            v2Logic().actions.setTileInView(tiles[13].id, true)
            v2Logic().actions.setTileInView(tiles[0].id, true)
            v2Logic().actions.setTileInView(tiles[13].id, true)
        }).toFinishAllListeners()

        expect(loadedShortIds().slice(12)).toEqual(['long-13'])
        expect(refreshInsight.mock.calls[12][4]).toEqual('blocking')
        expect(logic.values.refreshStatus['long-0']).toMatchObject({ refreshed: true })
        expect(v2Logic().values.deferredTileIds).toEqual([tiles[12].id, tiles[14].id])
    })

    it('loads a tile past the first screen that was already in view when the first load started', async () => {
        setDashboardV2(true)
        logic = dashboardLogic({ id: 21 })
        logic.mount()
        v2Logic().actions.setTileInView(tiles[13].id, true)
        await expectLogic(logic).toFinishAllListeners()

        expect(loadedShortIds()).toContain('long-13')
        expect(v2Logic().values.deferredTileIds).toEqual([tiles[12].id, tiles[14].id])
    })

    it('loads a deferred tile with the filters of the load that skipped it', async () => {
        setDashboardV2(true)
        router.actions.push(urls.dashboard(21), { query_filters: JSON.stringify({ date_from: '-3d' }) })
        logic = dashboardLogic({ id: 21 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        refreshInsight.mockClear()

        await expectLogic(logic, () => {
            logic.actions.setInitialDashboardSettingsOverride({ filters: { date_from: '-30d' }, variables: {} })
            v2Logic().actions.setTileInView(tiles[13].id, true)
        }).toFinishAllListeners()

        expect(loadedShortIds()).toEqual(['long-13'])
        expect(refreshInsight.mock.calls[0][6]).toMatchObject({ date_from: '-3d' })
    })

    it('auto refresh queries the tiles in view and refreshes a hidden tile once it scrolls back in', async () => {
        setDashboardV2(true)
        logic = dashboardLogic({ id: 21 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic, () => {
            v2Logic().actions.setTileInView(tiles[0].id, true)
            v2Logic().actions.setTileInView(tiles[1].id, true)
        }).toFinishAllListeners()
        refreshInsight.mockClear()

        await autoRefresh()

        expect(loadedShortIds()).toEqual(['long-0', 'long-1'])

        await expectLogic(logic, () => {
            v2Logic().actions.setTileInView(tiles[1].id, false)
            v2Logic().actions.setTileInView(tiles[7].id, true)
        }).toFinishAllListeners()

        expect(loadedShortIds()).toEqual(['long-0', 'long-1', 'long-7'])
        expect(refreshInsight.mock.calls.map((call) => call[4])).toEqual([
            'force_blocking',
            'force_blocking',
            'force_blocking',
        ])

        // Scrolled to a region with no insights: an automatic refresh queries none.
        await expectLogic(logic, () => {
            v2Logic().actions.setTileInView(tiles[0].id, false)
            v2Logic().actions.setTileInView(tiles[7].id, false)
        }).toFinishAllListeners()
        refreshInsight.mockClear()

        await autoRefresh()

        expect(loadedShortIds()).toEqual([])
    })

    it.each([
        { dashboardV2: true, kind: NodeKind.MetricsQuery, requestsStarted: 3, analyticsTileStarts: true },
        { dashboardV2: true, kind: NodeKind.MetricsHistogramQuery, requestsStarted: 3, analyticsTileStarts: true },
    ])(
        'with dashboard-v2 $dashboardV2, an analytics tile starts while $kind tiles fill their queue: $analyticsTileStarts',
        async ({ dashboardV2, kind, requestsStarted, analyticsTileStarts }) => {
            setDashboardV2(dashboardV2)
            const metricsTiles = tiles.slice(0, 5).map((tile) => ({
                ...tile,
                insight: { ...tile.insight!, query: { kind } as any },
            }))
            const analyticsTile = tiles[5]
            useMocks({
                get: {
                    '/api/environments/:team_id/dashboards/21/': () => [
                        200,
                        dashboardResult(21, [...metricsTiles, analyticsTile]),
                    ],
                },
            })
            refreshInsight.mockImplementation((_teamId, insight) =>
                insight.query?.kind === kind ? new Promise(() => {}) : Promise.resolve(insight)
            )
            logic = dashboardLogic({ id: 21 })
            logic.mount()

            await waitFor(() => expect(refreshInsight).toHaveBeenCalledTimes(requestsStarted))
            expect(loadedShortIds().includes(analyticsTile.insight!.short_id)).toBe(analyticsTileStarts)
        }
    )

    it('a manual refresh queries every tile, even with dashboard-v2', async () => {
        setDashboardV2(true)
        logic = dashboardLogic({ id: 21 })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        v2Logic().actions.setTileInView(tiles[0].id, true)
        refreshInsight.mockClear()

        await expectLogic(logic, () => {
            logic.actions.triggerDashboardRefresh()
        }).toFinishAllListeners()

        expect(loadedShortIds()).toEqual(tiles.map((tile) => tile.insight!.short_id))
        expect(v2Logic().values.deferredTileIds).toEqual([])
    })
})
