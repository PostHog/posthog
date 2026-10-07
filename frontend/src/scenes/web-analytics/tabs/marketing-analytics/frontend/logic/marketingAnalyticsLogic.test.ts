import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    ConversionGoalFilter,
    MARKETING_INTEGRATION_CONFIGS,
    DatabaseSchemaDataWarehouseTable,
    InsightVizNode,
    TrendsQuery,
    DataTableNode,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsSearchRow,
    MarketingAnalyticsOrderBy,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsColumnsSchemaNames,
    NodeKind,
    SourceMap,
    WebAnalyticsPropertyFilters,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    ExternalDataJobStatus,
    ExternalDataSchemaStatus,
    ExternalDataSource,
    ExternalDataSourceSchema,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { SEARCH_PERFORMANCE_QUERY_KEY } from 'products/marketing_analytics/frontend/search/searchPerformance'
import { searchPerformanceLogic } from 'products/marketing_analytics/frontend/search/searchPerformanceLogic'

import {
    MarketingAnalyticsTab,
    MarketingSourceStatus,
    MarketingDashboardView,
    SetupSection,
    marketingAnalyticsLogic,
} from './marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from './marketingAnalyticsSettingsLogic'
import { marketingAnalyticsTableLogic } from './marketingAnalyticsTableLogic'
import { marketingAnalyticsTilesLogic } from './marketingAnalyticsTilesLogic'

jest.mock('posthog-js')

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

    it('keeps the search date range in the URL when restoring a tab', async () => {
        router.actions.push(urls.marketingAnalyticsApp(), {
            tab: MarketingAnalyticsTab.SEARCH_PERFORMANCE,
            date_from: '-28d',
            compare: 'true',
        })
        logic = marketingAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.dateFilter.dateFrom).toBe('-28d')
        expect(router.values.searchParams).toMatchObject({
            date_from: '-28d',
            tab: MarketingAnalyticsTab.SEARCH_PERFORMANCE,
        })
    })

    it('keeps a connected Search Console integration selected after refreshing sources', async () => {
        logic = marketingAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setIntegrationFilter({
            integrationSourceIds: ['organic', 'deleted'],
            includeNonIntegrated: false,
        })
        await expectLogic(logic, () =>
            logic.actions.loadSourcesSuccess({
                count: 1,
                next: null,
                previous: null,
                results: [
                    {
                        id: 'organic',
                        source_id: 'example.com',
                        connection_id: 'example-organic',
                        source_type: 'GoogleSearchConsole',
                        schemas: [
                            {
                                name: 'search_analytics_by_query_page',
                                should_sync: true,
                                last_synced_at: dayjs(),
                                sync_frequency: '24hour',
                                table: { name: 'organic_query_pages', hogql_name: 'organic_query_pages' },
                            } as ExternalDataSourceSchema,
                        ],
                        status: ExternalDataJobStatus.Completed,
                        prefix: null,
                        description: 'example.com',
                        created_via: 'web',
                        latest_error: null,
                        sync_frequency: '24hour',
                        job_inputs: {},
                        user_access_level: AccessControlLevel.Admin,
                        revenue_analytics_config: { enabled: false, include_invoiceless_charges: false },
                    },
                ],
            })
        ).toFinishAllListeners()
        expect(logic.values.integrationFilter.integrationSourceIds).toEqual(['organic'])
        const searchLogic = searchPerformanceLogic()
        const unmountSearch = searchLogic.mount()
        try {
            expect(searchLogic.values.missingSources).toEqual(['GoogleAds'])
            logic.actions.setCompareFilter({ compare: true })
            logic.actions.setDates('-28d', null)
            searchLogic.actions.setChannel('paid')
            searchLogic.actions.setQuerySearch('missing query')
            expect(searchLogic.values.hasActiveFilters).toBe(true)
            expect(searchLogic.values.sources).toEqual([])

            searchLogic.actions.clearFilters()
            expect(searchLogic.values.hasActiveFilters).toBe(false)
            expect(searchLogic.values.sources.map((source) => source.id)).toEqual(['organic'])
            expect(searchLogic.values.query.search).toBe('')
            expect(logic.values.compareFilter).toEqual({ compare: true })
            const organicSource = logic.values.dataWarehouseSources!.results[0]
            await expectLogic(logic, () =>
                logic.actions.loadSourcesSuccess({
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        organicSource,
                        {
                            ...organicSource,
                            id: 'organic-other',
                            schemas: [
                                {
                                    ...organicSource.schemas[0],
                                    table: {
                                        ...organicSource.schemas[0].table!,
                                        name: 'other_query_pages',
                                        hogql_name: 'other_query_pages',
                                    },
                                },
                            ],
                        },
                    ],
                })
            ).toFinishAllListeners()
            logic.actions.setIntegrationFilter({ integrationSourceIds: ['organic'] })
            searchLogic.actions.selectRow({
                platform: 'GoogleSearchConsole',
                keyword: 'analytics',
                page: null,
            } as MarketingAnalyticsSearchRow)
            expect(searchLogic.values.detailQuery?.sources.map((source) => source.statsTable)).toEqual([
                'organic_query_pages',
            ])
            searchLogic.actions.selectRow({
                platform: 'GoogleAds',
                keyword: 'analytics',
                page: null,
            } as MarketingAnalyticsSearchRow)
            expect(searchLogic.values.detailQuery?.sources.map((source) => source.statsTable)).toEqual([
                'organic_query_pages',
                'other_query_pages',
            ])
        } finally {
            unmountSearch()
        }
    })

    it.each<{
        description: string
        overrideFromUrl?: boolean
        tab?: MarketingAnalyticsTab
        clearDraft?: boolean
        saveDraft?: boolean
        removeDraftColumn?: boolean
        orderBy?: MarketingAnalyticsOrderBy[]
        expectedOrderBy?: MarketingAnalyticsOrderBy[]
    }>([
        { description: 'active draft' },
        { description: 'URL override', overrideFromUrl: true },
        {
            description: 'Ad performance URL override',
            overrideFromUrl: true,
            tab: MarketingAnalyticsTab.AD_PERFORMANCE,
        },
        {
            description: 'cleared draft sorted by its goal',
            clearDraft: true,
            orderBy: [['Draft purchase', 'DESC']],
            expectedOrderBy: [],
        },
        { description: 'cleared draft without sorting', clearDraft: true, orderBy: [], expectedOrderBy: [] },
        { description: 'cleared draft sorted by a saved column', clearDraft: true },
        { description: 'saved draft goal', saveDraft: true },
        { description: 'draft cleared by removing one column', removeDraftColumn: true },
    ])(
        'restores campaign columns on a fresh visit: $description',
        async ({
            overrideFromUrl = false,
            tab,
            clearDraft = false,
            saveDraft = false,
            removeDraftColumn = false,
            orderBy = [['Clicks', 'DESC']],
            expectedOrderBy = [['Clicks', 'DESC']],
        }) => {
            const mountTable = async (): Promise<ReturnType<typeof marketingAnalyticsTilesLogic.build>> => {
                logic = marketingAnalyticsLogic()
                logic.mount()
                const tiles = marketingAnalyticsTilesLogic()
                tiles.mount()
                await expectLogic(logic).toFinishAllListeners()
                return tiles
            }
            let tiles = await mountTable()
            const select = [MarketingAnalyticsBaseColumns.Campaign, MarketingAnalyticsBaseColumns.Clicks]
            const pinnedColumns = [MarketingAnalyticsBaseColumns.Clicks]
            const expectedPinnedColumns = saveDraft ? [...pinnedColumns, 'Draft purchase'] : pinnedColumns
            logic.actions.setDraftConversionGoal({
                kind: NodeKind.EventsNode,
                event: 'purchase',
                conversion_goal_id: 'draft-purchase',
                conversion_goal_name: 'Draft purchase',
                schema_map: {},
            })
            await expectLogic(marketingAnalyticsTableLogic, () =>
                marketingAnalyticsTableLogic.actions.setQuery({
                    ...tiles.values.campaignCostsBreakdown!,
                    pinnedColumns: [...pinnedColumns, 'Draft purchase'],
                    source: {
                        ...(tiles.values.campaignCostsBreakdown!.source as MarketingAnalyticsTableQuery),
                        select: [...select, 'Draft purchase', 'Cost per Draft purchase'],
                        orderBy,
                    },
                })
            ).toFinishAllListeners()
            if (saveDraft) {
                await expectLogic(logic, () => logic.actions.saveConversionGoal()).toFinishAllListeners()
                expect(marketingAnalyticsTableLogic.values.defaultColumns).toContain('Draft purchase')
            }
            if (removeDraftColumn) {
                await expectLogic(marketingAnalyticsTableLogic, () =>
                    marketingAnalyticsTableLogic.actions.setQuery({
                        ...tiles.values.campaignCostsBreakdown!,
                        source: {
                            ...(tiles.values.campaignCostsBreakdown!.source as MarketingAnalyticsTableQuery),
                            select: [...select, 'Draft purchase'],
                        },
                    })
                ).toFinishAllListeners()
                expect(logic.values.draftConversionGoal).toBeNull()
            }
            if (clearDraft) {
                await expectLogic(logic, () => logic.actions.clearConversionGoal()).toFinishAllListeners()
                expect(marketingAnalyticsTableLogic.values.query).toMatchObject({
                    pinnedColumns,
                    source: { select },
                })
                expect(
                    (marketingAnalyticsTableLogic.values.query?.source as MarketingAnalyticsTableQuery).orderBy ?? []
                ).toEqual(expectedOrderBy)
            }
            const savedColumns = JSON.parse(
                localStorage.getItem(
                    `${MOCK_TEAM_ID}__.scenes.marketingAnalytics.marketingAnalyticsTableLogic.columnConfiguration`
                )!
            )
            expect({ ...savedColumns, orderBy: savedColumns.orderBy ?? [] }).toEqual({
                select,
                pinnedColumns: expectedPinnedColumns,
                orderBy: expectedOrderBy,
            })
            tiles.unmount()
            logic.unmount()

            initKeaTests()
            router.actions.push(
                urls.marketingAnalyticsApp(),
                overrideFromUrl ? { tab, select: 'Campaign,Cost', order_column: 'Cost', order_direction: 'ASC' } : {}
            )
            tiles = await mountTable()
            try {
                expect(tiles.values.campaignCostsBreakdown).toMatchObject({
                    pinnedColumns: overrideFromUrl ? [] : expectedPinnedColumns,
                    source: {
                        select: overrideFromUrl ? ['Campaign', 'Cost'] : ['Clicks', 'Campaign'],
                        orderBy: overrideFromUrl ? [['Cost', 'ASC']] : expectedOrderBy,
                    },
                })
            } finally {
                tiles.unmount()
            }
        }
    )

    it('uses default columns for empty column URL parameters', async () => {
        router.actions.push(urls.marketingAnalyticsApp(), { select: null, pinned_columns: null })
        logic = marketingAnalyticsLogic()
        logic.mount()
        const tiles = marketingAnalyticsTilesLogic()
        tiles.mount()
        try {
            await expectLogic(logic).toFinishAllListeners()
            expect(tiles.values.campaignCostsBreakdown).toMatchObject({
                pinnedColumns: [],
                source: { select: marketingAnalyticsTableLogic.values.defaultColumns, orderBy: [] },
            })
        } finally {
            tiles.unmount()
        }
    })

    it('excludes conversion queries only in Ad performance and preserves legacy columns', async () => {
        logic = marketingAnalyticsLogic()
        logic.mount()
        const tiles = marketingAnalyticsTilesLogic()
        tiles.mount()
        const search = searchPerformanceLogic()
        search.mount()
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
            search.actions.setMetrics('conversions')
            expect(search.values.query.includePostHogConversions).toBe(false)
            search.actions.setBreakdown('page')
            expect(search.values.query.includePostHogConversions).toBe(true)
            const searchNode = dataNodeLogic({
                key: SEARCH_PERFORMANCE_QUERY_KEY,
                query: search.values.query,
                autoLoad: false,
            })
            searchNode.mount()
            const reloadSearch = jest.spyOn(searchNode.actions, 'loadData')
            const saveSetting = (config: Record<string, unknown>): void => {
                teamLogic.actions.updateCurrentTeamSuccess(teamLogic.values.currentTeam!, {
                    marketing_analytics_config: config,
                })
            }
            saveSetting({ attribution_window_days: 30 })
            expect(reloadSearch).not.toHaveBeenCalled()
            saveSetting({ filter_test_accounts: true })
            expect(reloadSearch).toHaveBeenCalledWith('force_async')
            search.actions.setMetrics('traffic')
            expect(search.values.query.includePostHogConversions).toBe(false)
            saveSetting({ filter_test_accounts: false })
            expect(reloadSearch).toHaveBeenCalledTimes(1)
            await expectLogic(searchNode).toFinishAllListeners()
            searchNode.unmount()
            search.actions.setMetrics('conversions')
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
                expect(search.values.query.includePostHogConversions).toBe(true)
                const chartBefore = (tiles.values.marketingChartTile.query as InsightVizNode).source as TrendsQuery
                logic.actions.setAdPerformanceConversionGoals(false)
                expect(search.values.query.includePostHogConversions).toBe(false)
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
            search.unmount()
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
        const search = searchPerformanceLogic()
        search.mount()
        search.actions.setBreakdown('page')
        search.actions.setMetrics('conversions')
        expect(search.values.displayMetrics).toBe('traffic')
        expect(search.values.conversionsDisabledReason).toContain('Configure a conversion goal')
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
        expect(search.values.displayMetrics).toBe('conversions')
        expect(search.values.conversionsDisabledReason).toBeNull()
        logic.actions.setAdPerformanceConversionGoals(false)
        expect(search.values.displayMetrics).toBe('traffic')
        expect(search.values.conversionsDisabledReason).toContain('Include conversion goals')
        search.unmount()
    })

    it('separates an ad source missing its required tables from having no source at all', async () => {
        logic = marketingAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const metaSource = (shouldSync: boolean): ExternalDataSource =>
            ({
                id: 'meta-source',
                source_type: 'MetaAds',
                schemas: [
                    { id: 'campaigns', name: 'campaigns', should_sync: shouldSync },
                    { id: 'campaign_stats', name: 'campaign_stats', should_sync: shouldSync },
                ],
            }) as ExternalDataSource

        await expectLogic(logic, () =>
            logic.actions.loadSourcesSuccess({ count: 1, next: null, previous: null, results: [metaSource(false)] })
        ).toFinishAllListeners()
        databaseTableListLogic.actions.loadDatabaseSuccess({ tables: {}, joins: [] })

        expect(logic.values.hasNoConfiguredSources).toBe(true)
        expect(logic.values.unconfiguredNativeSources.map((source) => source.id)).toEqual(['meta-source'])

        await expectLogic(logic, () =>
            logic.actions.loadSourcesSuccess({ count: 1, next: null, previous: null, results: [metaSource(true)] })
        ).toFinishAllListeners()

        expect(logic.values.unconfiguredNativeSources).toEqual([])
    })

    it('shows validation errors for the affected connection and clears them after reload', async () => {
        let errors: Record<string, string[]> = {}
        useMocks({
            get: {
                '/api/projects/:team_id/marketing_analytics/source_validation/': () => [
                    200,
                    { errors_by_source: errors },
                ],
            },
        })
        logic = marketingAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_OPENAI_ADS]: true })
        const sources = ['outdated', 'current'].map(
            (id) =>
                ({
                    id,
                    source_type: 'OpenAIAds',
                    schemas: ['campaigns', 'campaign_insights'].map((name) => ({
                        id: `${id}-${name}`,
                        name,
                        should_sync: true,
                        status: ExternalDataSchemaStatus.Completed,
                    })),
                }) as ExternalDataSource
        )
        await expectLogic(logic, () =>
            logic.actions.loadSourcesSuccess({ count: 2, next: null, previous: null, results: sources })
        ).toFinishAllListeners()
        expect(logic.values.allAvailableSourcesWithStatus.every(({ status }) => status === 'Completed')).toBe(true)

        errors = { outdated: ["Missing 'currency_code' in 'campaign_insights'.", "Missing 'name' in 'campaigns'."] }
        await expectLogic(logic, () => logic.actions.reloadAll()).toFinishAllListeners()
        for (const sourcesWithStatus of [
            logic.values.allAvailableSourcesWithStatus,
            logic.values.allExternalTablesWithStatus,
        ]) {
            expect(sourcesWithStatus.find((source) => source.id === 'outdated')).toMatchObject({
                status: MarketingSourceStatus.Warning,
                statusMessage: expect.stringContaining(errors.outdated.join(' ')),
            })
            expect(sourcesWithStatus.find((source) => source.id === 'current')?.status).toBe('Completed')
        }
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_OPENAI_ADS]: false })
        expect(logic.values.allAvailableSourcesWithStatus).toEqual([])
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_OPENAI_ADS]: true })
        errors = {}
        await expectLogic(logic, () => logic.actions.reloadAll()).toFinishAllListeners()
        for (const sourcesWithStatus of [
            logic.values.allAvailableSourcesWithStatus,
            logic.values.allExternalTablesWithStatus.filter((source) => sources.some(({ id }) => id === source.id)),
        ]) {
            expect(sourcesWithStatus.map(({ status }) => status)).toEqual(['Completed', 'Completed'])
        }
        useMocks({
            get: { '/api/projects/:team_id/marketing_analytics/source_validation/': () => [500, {}] },
        })
        await expectLogic(logic, () => logic.actions.loadSourceValidation()).toFinishAllListeners()
        expect(logic.values.sourceValidationError).not.toBeNull()
        useMocks({
            get: {
                '/api/projects/:team_id/marketing_analytics/source_validation/': () => [200, { errors_by_source: {} }],
            },
        })
        await expectLogic(logic, () => logic.actions.loadSourceValidation()).toFinishAllListeners()
        expect(logic.values.sourceValidationError).toBeNull()
    })

    it.each(['managed', 'self-managed'])('shows invalid mappings for a %s source until corrected', async (type) => {
        const tableId = 'example-table'
        const sourceId = type === 'managed' ? 'example-schema' : tableId
        let errors: Record<string, string[]> = { [sourceId]: ['Missing required column mapping: cost'] }
        useMocks({
            get: {
                '/api/projects/:team_id/marketing_analytics/source_validation/': () => [
                    200,
                    { errors_by_source: errors },
                ],
            },
        })
        logic = marketingAnalyticsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        databaseTableListLogic.actions.loadDatabaseSuccess({
            tables: {
                example_campaigns: {
                    id: tableId,
                    name: 'example_campaigns',
                    type: 'data_warehouse',
                    url_pattern: 'https://example.s3.amazonaws.com/campaigns',
                    ...(type === 'managed'
                        ? {
                              schema: {
                                  id: sourceId,
                                  name: 'example_campaigns',
                                  should_sync: true,
                                  incremental: false,
                                  status: ExternalDataSchemaStatus.Completed,
                              },
                              source: {
                                  id: 'example-source',
                                  source_type: 'BigQuery',
                                  status: 'Completed',
                                  prefix: '',
                              },
                          }
                        : {}),
                    fields: {
                        cost: { name: 'cost', hogql_value: 'cost', type: 'float', schema_valid: true },
                    },
                } satisfies DatabaseSchemaDataWarehouseTable,
            },
            joins: [],
        })

        for (const sourceMap of [{}, { campaign: 'campaign' }] as SourceMap[]) {
            await expectLogic(logic, () =>
                teamLogic.actions.loadCurrentTeamSuccess({
                    ...teamLogic.values.currentTeam!,
                    marketing_analytics_config: { sources_map: { [sourceId]: sourceMap } },
                })
            ).toFinishAllListeners()
            expect(logic.values.validExternalTables).toEqual([])
            expect(logic.values.allAvailableSources).toEqual([])
            expect(logic.values.allAvailableSourcesWithStatus).toEqual([
                expect.objectContaining({
                    id: sourceId,
                    status: MarketingSourceStatus.Warning,
                    statusMessage: expect.stringContaining(errors[sourceId][0]),
                }),
            ])
        }
        await expectLogic(logic, () =>
            teamLogic.actions.loadCurrentTeamSuccess({
                ...teamLogic.values.currentTeam!,
                marketing_analytics_config: {
                    sources_map: {
                        [sourceId]: Object.fromEntries(
                            Object.values(MarketingAnalyticsColumnsSchemaNames).map((name) => [name, name])
                        ) as SourceMap,
                    },
                },
            })
        ).toFinishAllListeners()
        errors = {}
        await expectLogic(logic, () => logic.actions.reloadAll()).toFinishAllListeners()
        expect(logic.values.validExternalTables).toHaveLength(1)
        expect(logic.values.allAvailableSourcesWithStatus).toEqual([
            expect.objectContaining({ id: sourceId, status: ExternalDataSchemaStatus.Completed }),
        ])
    })

    it('keeps the selection and drops an unknown key from a filter saved by an older build', async () => {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ integrationSourceIds: ['source-1'], removedOption: true }))

        logic = marketingAnalyticsLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            integrationFilter: { integrationSourceIds: ['source-1'] },
        })
    })

    it.each(['tab', 'scene'] as const)(
        'clears the dashboard setup entry point when leaving the %s',
        async (destination) => {
            const settings = marketingAnalyticsSettingsLogic()
            const unmountSettings = settings.mount()
            logic = marketingAnalyticsLogic()
            logic.mount()

            await expectLogic(logic, () =>
                logic.actions.openSetup(SetupSection.CONVERSION_GOALS, 'dashboard_customer_cards')
            )
                .toFinishAllListeners()
                .toMatchValues({
                    activeTab: MarketingAnalyticsTab.SETUP,
                    setupSection: SetupSection.CONVERSION_GOALS,
                    setupEntryPoint: 'dashboard_customer_cards',
                })
            expect(posthog.capture).toHaveBeenCalledWith('marketing analytics dashboard setup opened', {
                entry_point: 'dashboard_customer_cards',
                section: SetupSection.CONVERSION_GOALS,
            })

            await expectLogic(logic, () => logic.actions.setSetupSection(SetupSection.SOURCES))
                .toFinishAllListeners()
                .toMatchValues({ setupEntryPoint: 'dashboard_customer_cards' })
            if (destination === 'tab') {
                await expectLogic(logic, () =>
                    logic.actions.setActiveTab(MarketingAnalyticsTab.DASHBOARD)
                ).toFinishAllListeners()
            } else {
                logic.unmount()
            }
            expect(settings.values.setupEntryPoint).toBeNull()
            unmountSettings()
        }
    )
    it('carries dashboard view, breakdown and filters in the URL', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD], {
            [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]: true,
        })
        logic = marketingAnalyticsLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.setDates('-30d', null)).toFinishAllListeners()
        expect(router.values.searchParams).not.toHaveProperty('view')
        expect(router.values.searchParams).not.toHaveProperty('breakdown')
        expect(new URLSearchParams(router.values.location.search).get('date_to')).toBe('')

        const filters: WebAnalyticsPropertyFilters = [
            {
                type: PropertyFilterType.Session,
                key: '$channel_type',
                operator: PropertyOperator.Exact,
                value: 'Direct',
            },
        ]
        logic.actions.setDashboardView(MarketingDashboardView.ENGAGEMENT)
        logic.actions.setDashboardBreakdown(MarketingAnalyticsAttributionBreakdown.Campaign)
        logic.actions.setDashboardProperties(filters)
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams).toMatchObject({
            view: 'engagement',
            breakdown: 'campaign',
            filters,
        })

        await expectLogic(logic, () => logic.actions.setDates('-7d', null)).toFinishAllListeners()
        expect(router.values.searchParams).toMatchObject({ view: 'engagement', breakdown: 'campaign', filters })

        logic.actions.setDashboardView(MarketingDashboardView.OVERVIEW)
        logic.actions.setDashboardBreakdown(MarketingAnalyticsAttributionBreakdown.Channel)
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.searchParams).toMatchObject({ view: 'overview', breakdown: 'channel' })
        expect(new URLSearchParams(router.values.location.search).get('date_to')).toBe('')

        await expectLogic(logic, () =>
            router.actions.push(urls.marketingAnalyticsApp(), { view: 'retention', breakdown: 'source' })
        ).toMatchValues({
            dashboardView: MarketingDashboardView.RETENTION,
            dashboardBreakdown: MarketingAnalyticsAttributionBreakdown.Source,
            dashboardProperties: [],
        })

        await expectLogic(logic, () => router.actions.push(urls.marketingAnalyticsApp())).toMatchValues({
            dashboardView: MarketingDashboardView.OVERVIEW,
            dashboardBreakdown: MarketingAnalyticsAttributionBreakdown.Channel,
            dashboardProperties: [],
        })
    })

    it.each([
        {
            search: { view: 'retention' },
            savedBreakdown: 'campaign',
            expectedView: MarketingDashboardView.RETENTION,
            expectedBreakdown: MarketingAnalyticsAttributionBreakdown.Channel,
        },
        {
            search: { breakdown: 'source' },
            savedBreakdown: 'campaign',
            expectedView: MarketingDashboardView.OVERVIEW,
            expectedBreakdown: MarketingAnalyticsAttributionBreakdown.Source,
        },
        {
            search: {},
            savedBreakdown: 'campaign',
            expectedView: MarketingDashboardView.ENGAGEMENT,
            expectedBreakdown: MarketingAnalyticsAttributionBreakdown.Campaign,
        },
        {
            search: { view: 'retention' },
            savedBreakdown: 'retired_dimension',
            expectedView: MarketingDashboardView.RETENTION,
            expectedBreakdown: MarketingAnalyticsAttributionBreakdown.Channel,
        },
    ])(
        'hydrates $search with persisted breakdown $savedBreakdown',
        async ({ search, savedBreakdown, expectedView, expectedBreakdown }) => {
            localStorage.setItem(
                `${MOCK_TEAM_ID}__.scenes.webAnalytics.marketingAnalyticsLogic._dashboardView`,
                JSON.stringify(MarketingDashboardView.ENGAGEMENT)
            )
            localStorage.setItem(
                `${MOCK_TEAM_ID}__.scenes.webAnalytics.marketingAnalyticsLogic._dashboardBreakdown`,
                JSON.stringify(savedBreakdown)
            )
            router.actions.push(urls.marketingAnalyticsApp(), search)

            logic = marketingAnalyticsLogic()
            logic.mount()

            await expectLogic(logic).toMatchValues({
                dashboardView: expectedView,
                dashboardBreakdown: expectedBreakdown,
                dashboardProperties: [],
            })
        }
    )

    it.each([
        ['?date_from=-7d&date_to=', { dateFrom: '-7d', dateTo: null }],
        ['?date_from=-7d&date_to=&tab=setup&section=sources', { dateFrom: '-7d', dateTo: null }],
        ['?date_from=-7d&date_to=-1d', { dateFrom: '-7d', dateTo: '-1d' }],
        ['', { dateFrom: '-30d', dateTo: '2026-08-31' }],
    ])('hydrates the date range from "%s" over a saved range', async (search, expected) => {
        localStorage.setItem(
            `${MOCK_TEAM_ID}__.scenes.webAnalytics.marketingAnalyticsLogic.dateFilter`,
            JSON.stringify({ dateFrom: '-30d', dateTo: '2026-08-31', interval: 'day' })
        )
        router.actions.push(`${urls.marketingAnalyticsApp()}${search}`)

        logic = marketingAnalyticsLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ dateFilter: expect.objectContaining(expected) })
    })

    it.each([
        ['AppleSearchAds', FEATURE_FLAGS.MARKETING_ANALYTICS_APPLE_ADS],
        ['OpenAIAds', FEATURE_FLAGS.MARKETING_ANALYTICS_OPENAI_ADS],
        ['AmazonAds', FEATURE_FLAGS.MARKETING_ANALYTICS_AMAZON_ADS],
        ['RoktAds', FEATURE_FLAGS.MARKETING_ANALYTICS_ROKT_ADS],
    ] as const)(
        'removes %s from connected sources and mapping menus when its flag turns off',
        async (sourceType, flag) => {
            logic = marketingAnalyticsLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const campaignSchema = MARKETING_INTEGRATION_CONFIGS[sourceType].campaignTableName
            await expectLogic(logic, () =>
                logic.actions.loadSourcesSuccess({
                    count: 2,
                    next: null,
                    previous: null,
                    results: [
                        { id: 'new-source', source_type: sourceType, schemas: [] } as unknown as ExternalDataSource,
                        { id: 'google-source', source_type: 'GoogleAds', schemas: [] } as unknown as ExternalDataSource,
                    ],
                })
            ).toFinishAllListeners()
            databaseTableListLogic.actions.loadDatabaseSuccess({
                tables: {
                    campaign: {
                        id: 'campaign-table',
                        name: `${sourceType}_${campaignSchema}`,
                        type: 'data_warehouse',
                        source: { id: 'new-source', source_type: sourceType },
                        fields: {},
                    } as DatabaseSchemaDataWarehouseTable,
                },
                joins: [],
            })
            for (const enabled of [false, true, false]) {
                featureFlagLogic.actions.setFeatureFlags([], { [flag]: enabled })
                expect(logic.values.nativeSources.map((source) => source.source_type)).toEqual(
                    enabled ? [sourceType, 'GoogleAds'] : ['GoogleAds']
                )
                expect(marketingAnalyticsSettingsLogic.values.integrationCampaignTables[sourceType]).toBe(
                    enabled ? `${sourceType}_${campaignSchema}` : undefined
                )
            }
        }
    )
})
