import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'
import { AttributionTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTab'
import { AttributionTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTable'
import { RetentionTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/RetentionTab/RetentionTab'
import {
    MarketingAnalyticsTab,
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAttributionLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAttributionLogic'
import { BREAKDOWN_LABELS } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'
import { MarketingAnalyticsCell } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/shared'
import { webAnalyticsDataTableQueryContext } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { OverviewMetricCardGrid } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'
import { Query } from '~/queries/Query/Query'
import {
    DataTableNode,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsDrillDownLevel,
    NodeKind,
    WebOverviewQuery,
    WebOverviewQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'

// Channel is the top level because it covers all traffic, not just the platforms with a
// connected ad source. Source is the second column so a channel breaks down into the
// sources that make it up.
const COLUMNS: string[] = [
    'Channel',
    MarketingAnalyticsBaseColumns.Source,
    // Sessions comes from the sessions table, so it's the only column that has a value for
    // traffic with no ad spend behind it (organic, direct, referral).
    'Sessions',
    MarketingAnalyticsBaseColumns.Cost,
    MarketingAnalyticsBaseColumns.Clicks,
    MarketingAnalyticsBaseColumns.Impressions,
    MarketingAnalyticsBaseColumns.CPC,
    MarketingAnalyticsBaseColumns.CTR,
]

const CHANNEL_SOURCE_BREAKDOWN: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.MarketingAnalyticsTableQuery,
        dateRange: { date_from: '-30d', date_to: null },
        drillDownLevel: MarketingAnalyticsDrillDownLevel.ChannelSource,
        select: COLUMNS,
        // Sort by channel first so every source of a channel lands together, then by traffic
        // within the channel — sessions is the one metric every row has.
        orderBy: [
            ['Channel', 'ASC'],
            ['Sessions', 'DESC'],
        ],
        properties: [],
        limit: 200,
        tags: MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS,
    },
    full: true,
    embedded: false,
    showOpenEditorButton: false,
    showElapsedTime: true,
    showTimings: true,
}

// Every cell is a MarketingAnalyticsItem, not a scalar — without a render fn the table falls
// through to the raw JSON viewer.
const QUERY_CONTEXT: QueryContext = {
    ...webAnalyticsDataTableQueryContext,
    columns: COLUMNS.reduce(
        (acc, column) => {
            acc[column] = { render: MarketingAnalyticsCell }
            return acc
        },
        {} as Record<string, QueryContextColumn>
    ),
}

// Scaffold for the redesigned marketing analytics dashboard, gated behind the
// `new-marketing-analytics-dashboard` feature flag.
export function NewMarketingAnalyticsDashboard(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { revenueGoals, selectedRevenueGoalId, revenueQuery, breakdownBy } = useValues(marketingAttributionLogic)
    const { setRevenueGoalId, setBreakdownBy } = useActions(marketingAttributionLogic)
    const { dateFilter, compareFilter, shouldFilterTestAccounts } = useValues(marketingAnalyticsLogic)
    const { setDates, setCompareFilter, setActiveTab, setSetupSection } = useActions(marketingAnalyticsLogic)
    const dateRange = { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo }
    const query: WebOverviewQuery = {
        kind: NodeKind.WebOverviewQuery,
        dateRange,
        compareFilter,
        filterTestAccounts: shouldFilterTestAccounts,
        properties: [],
        tags: MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS,
    }
    const overviewLogic = dataNodeLogic({ query, key: 'marketing-acquisition-overview' })
    const { response, responseLoading, responseError } = useValues(overviewLogic)
    const { loadData } = useActions(overviewLogic)
    const overview = response as WebOverviewQueryResponse | undefined

    return (
        <div className="mt-4 flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                <LemonButton size="small" loading={responseLoading} onClick={() => loadData('force_async')}>
                    Reload summary
                </LemonButton>
            </div>
            {responseError ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadData('force_async') }}>
                    Could not load traffic metrics. Try again.
                </LemonBanner>
            ) : (
                [
                    { title: 'Acquisition', keys: ['visitors', 'sessions', 'views'] },
                    { title: 'Engagement', keys: ['session duration', 'bounce rate'] },
                ].map(({ title, keys }) => (
                    <section key={title} className="flex flex-col gap-2" aria-label={title}>
                        <h2 className="mb-0">{title}</h2>
                        <OverviewMetricCardGrid
                            items={keys.flatMap((key) =>
                                (overview?.results?.filter((item) => item.key === key) ?? []).map((item) => ({
                                    ...item,
                                    value: item.value,
                                }))
                            )}
                            loading={responseLoading}
                            numSkeletons={keys.length}
                            samplingRate={overview?.samplingRate}
                            preComputeStrategy={overview?.preComputeStrategy}
                            labelFromKey={labelFromKey}
                        />
                    </section>
                ))
            )}
            {featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ATTRIBUTION] && (
                <section aria-label="Conversion" className="flex flex-col gap-2">
                    <h2 className="mb-0">Conversion</h2>
                    <AttributionTab />
                </section>
            )}
            {featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_RETENTION] && (
                <section aria-label="Retention" className="flex flex-col gap-2">
                    <h2 className="mb-0">Retention</h2>
                    <p className="text-secondary mb-0">
                        Follow visitors acquired in the selected date range across subsequent periods.
                    </p>
                    <RetentionTab />
                </section>
            )}
            {featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ATTRIBUTION] && (
                <section aria-label="Revenue" className="flex flex-col gap-4">
                    <h2 className="mb-0">Revenue</h2>
                    {currentTeamLoading || !currentTeam ? (
                        <LemonSkeleton className="h-40" />
                    ) : revenueQuery ? (
                        <>
                            <div className="flex flex-wrap items-center gap-2">
                                <DateFilter
                                    dateFrom={dateFilter.dateFrom}
                                    dateTo={dateFilter.dateTo}
                                    onChange={setDates}
                                />
                                <LemonSelect
                                    value={selectedRevenueGoalId}
                                    onChange={(value) => value && setRevenueGoalId(value)}
                                    options={revenueGoals.map((goal) => ({
                                        value: goal.conversion_goal_id,
                                        label: goal.conversion_goal_name,
                                    }))}
                                    data-attr="marketing-revenue-goal"
                                />
                                <LemonSelect
                                    value={breakdownBy}
                                    onChange={setBreakdownBy}
                                    options={Object.values(MarketingAnalyticsAttributionBreakdown).map((value) => ({
                                        value,
                                        label: BREAKDOWN_LABELS[value],
                                    }))}
                                    data-attr="marketing-revenue-breakdown"
                                />
                            </div>
                            <p className="text-secondary mb-0">
                                Compare attributed value across models for one revenue goal at a time.
                            </p>
                            <AttributionTable
                                metric="revenue"
                                query={revenueQuery}
                                attachTo={marketingAnalyticsLogic}
                            />
                        </>
                    ) : (
                        <LemonBanner
                            type="info"
                            action={{
                                children: 'Review in Setup',
                                onClick: () => {
                                    setSetupSection(SetupSection.CONVERSION_GOALS)
                                    setActiveTab(MarketingAnalyticsTab.SETUP)
                                },
                            }}
                        >
                            Choose an event or action goal that sums an amount and mark it as Revenue in Setup.
                        </LemonBanner>
                    )}
                </section>
            )}
            <Query
                query={{
                    ...CHANNEL_SOURCE_BREAKDOWN,
                    source: {
                        ...CHANNEL_SOURCE_BREAKDOWN.source,
                        dateRange,
                        compareFilter,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                }}
                context={QUERY_CONTEXT}
                readOnly
            />
        </div>
    )
}
