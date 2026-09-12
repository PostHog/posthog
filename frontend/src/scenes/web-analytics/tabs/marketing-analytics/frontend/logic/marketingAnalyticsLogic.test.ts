import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    ConversionGoalFilter,
    DatabaseSchemaDataWarehouseTable,
    InsightVizNode,
    TrendsQuery,
    DataTableNode,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsColumnsSchemaNames,
    NodeKind,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import { MarketingAnalyticsTab, marketingAnalyticsLogic } from './marketingAnalyticsLogic'
import { marketingAnalyticsTableLogic } from './marketingAnalyticsTableLogic'
import { marketingAnalyticsTilesLogic } from './marketingAnalyticsTilesLogic'

// Kea builds this from the reducer's path and name. It is pinned in the logic, so a rename cannot
// silently point the reducer at a different key and abandon what someone already saved.
const STORAGE_KEY = `${MOCK_TEAM_ID}__.scenes.webAnalytics.marketingAnalyticsLogic.integrationFilter`

describe('marketingAnalyticsLogic', () => {
    let logic: ReturnType<typeof marketingAnalyticsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        if (logic?.cache.mounted) {
            logic.unmount()
        }
        localStorage.clear()
    })

    it('excludes conversion queries only in Ad performance and preserves legacy columns', async () => {
        logic = marketingAnalyticsLogic()
        logic.mount()
        const tiles = marketingAnalyticsTilesLogic()
        tiles.mount()
        try {
            await expectLogic(logic).toFinishAllListeners()
            const goal: ConversionGoalFilter = {
                kind: NodeKind.EventsNode,
                event: 'purchase',
                conversion_goal_id: 'purchase-goal',
                conversion_goal_name: 'Purchases',
                schema_map: {},
            }
            await expectLogic(logic, () =>
                teamLogic.actions.loadCurrentTeamSuccess({
                    ...teamLogic.values.currentTeam!,
                    marketing_analytics_config: { conversion_goals: [goal] },
                })
            ).toFinishAllListeners()
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]: true })
            logic.actions.setActiveTab(MarketingAnalyticsTab.AD_PERFORMANCE)
            expect(logic.values.includeConversionGoals).toBe(true)
            const savedQuery: DataTableNode = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.MarketingAnalyticsTableQuery,
                    select: [
                        MarketingAnalyticsBaseColumns.Campaign,
                        'Purchases',
                        'Cost per Purchases',
                        'ROAS',
                        'Cost per Customer',
                    ],
                    orderBy: [['Purchases', 'DESC']],
                    properties: [],
                },
            }
            marketingAnalyticsTableLogic.actions.setQuery(savedQuery)
            logic.actions.setDraftConversionGoal({ ...goal, conversion_goal_name: 'Draft purchases' })
            await expectLogic(logic, () =>
                logic.actions.loadSourcesSuccess({
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 'google-source',
                            source_type: 'GoogleAds',
                            schemas: [
                                { id: 'campaign', name: 'campaign', should_sync: true },
                                { id: 'stats', name: 'campaign_overview_stats', should_sync: true },
                            ],
                        } as ExternalDataSource,
                    ],
                })
            ).toFinishAllListeners()
            databaseTableListLogic.actions.loadDatabaseSuccess({
                tables: {
                    campaign_overview_stats: {
                        id: 'stats-table',
                        name: 'campaign_overview_stats',
                        type: 'data_warehouse',
                        schema: { id: 'stats', name: 'campaign_overview_stats', should_sync: true, incremental: false },
                        fields: {
                            metrics_conversions: {
                                name: 'metrics_conversions',
                                hogql_value: 'metrics_conversions',
                                type: 'float',
                                schema_valid: true,
                            },
                        },
                    } satisfies DatabaseSchemaDataWarehouseTable,
                },
                joins: [],
            })
            logic.actions.setTileColumnSelection(MarketingAnalyticsColumnsSchemaNames.ReportedConversion)
            for (const precomputed of [false, true]) {
                featureFlagLogic.actions.setFeatureFlags([], {
                    [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]: true,
                    [FEATURE_FLAGS.MARKETING_ANALYTICS_COSTS_PRECOMPUTATION]: precomputed,
                })
                logic.actions.setAdPerformanceConversionGoals(true)
                const chartBefore = (tiles.values.marketingChartTile.query as InsightVizNode).source as TrendsQuery
                logic.actions.setAdPerformanceConversionGoals(false)
                const chartAfter = (tiles.values.marketingChartTile.query as InsightVizNode).source as TrendsQuery
                expect(chartAfter).toEqual(chartBefore)
                expect(chartAfter.series).toHaveLength(1)
                expect(chartAfter.series[0]).toMatchObject({
                    kind: NodeKind.DataWarehouseNode,
                    table_name: precomputed ? 'marketing_costs_precomputed' : 'campaign_overview_stats',
                    math_hogql: expect.stringContaining(precomputed ? 'reported_conversions' : 'metrics_conversions'),
                })
                expect(logic.values.tileColumnSelection).toBe('reported_conversion')
            }
            logic.actions.setAdPerformanceConversionGoals(false)
            const overview = tiles.values.overviewTile.query as MarketingAnalyticsAggregatedQuery
            const table = tiles.values.campaignCostsBreakdown!.source as MarketingAnalyticsTableQuery
            expect(overview.select).toEqual(Object.values(MarketingAnalyticsBaseColumns))
            expect(overview.draftConversionGoal).toBeUndefined()
            expect(table.select).toEqual([MarketingAnalyticsBaseColumns.Campaign])
            expect(table.draftConversionGoal).toBeNull()
            expect(table.orderBy).toEqual([])
            expect(marketingAnalyticsTableLogic.values.query).toEqual(savedQuery)
            logic.actions.setAdPerformanceConversionGoals(true)
            expect((tiles.values.campaignCostsBreakdown!.source as MarketingAnalyticsTableQuery).select).toContain(
                'Purchases'
            )
            logic.actions.setAdPerformanceConversionGoals(false)
            for (const legacyState of ['other-tab', 'flag-off'] as const) {
                logic.actions.setActiveTab(
                    legacyState === 'other-tab' ? MarketingAnalyticsTab.DASHBOARD : MarketingAnalyticsTab.AD_PERFORMANCE
                )
                featureFlagLogic.actions.setFeatureFlags([], {
                    [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]: legacyState !== 'flag-off',
                })
                expect(logic.values.includeConversionGoals).toBe(true)
                expect((tiles.values.overviewTile.query as MarketingAnalyticsAggregatedQuery).select).toBeUndefined()
                expect((tiles.values.campaignCostsBreakdown!.source as MarketingAnalyticsTableQuery).select).toContain(
                    'Purchases'
                )
                expect(marketingAnalyticsTableLogic.values.query).toEqual(savedQuery)
            }
        } finally {
            tiles.unmount()
        }
    })

    it('keeps conversion goals off until configured without changing the default preference', async () => {
        logic = marketingAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]: true })
        logic.actions.setActiveTab(MarketingAnalyticsTab.AD_PERFORMANCE)
        expect(logic.values.includeConversionGoals).toBe(false)
        expect(logic.values.adPerformanceConversionGoals).toBe(true)
        await expectLogic(logic, () =>
            teamLogic.actions.loadCurrentTeamSuccess({
                ...teamLogic.values.currentTeam!,
                marketing_analytics_config: {
                    conversion_goals: [
                        {
                            kind: NodeKind.EventsNode,
                            event: 'purchase',
                            conversion_goal_id: 'purchase-goal',
                            conversion_goal_name: 'Purchases',
                            schema_map: {},
                        },
                    ],
                },
            })
        ).toFinishAllListeners()
        expect(logic.values.includeConversionGoals).toBe(true)
    })

    it('keeps the selection and drops an unknown key from a filter saved by an older build', async () => {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ integrationSourceIds: ['source-1'], includeNonIntegrated: true })
        )

        logic = marketingAnalyticsLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            integrationFilter: { integrationSourceIds: ['source-1'] },
        })
    })
})
