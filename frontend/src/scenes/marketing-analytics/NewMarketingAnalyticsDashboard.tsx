import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { MarketingAnalyticsCell } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/shared'
import { webAnalyticsDataTableQueryContext } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { OverviewMetricCardGrid } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'
import { Query } from '~/queries/Query/Query'
import {
    DataTableNode,
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
    const { dateFilter, compareFilter, shouldFilterTestAccounts } = useValues(marketingAnalyticsLogic)
    const { setDates, setCompareFilter } = useActions(marketingAnalyticsLogic)
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
    const items = ['visitors', 'sessions', 'views'].flatMap((key) =>
        (overview?.results?.filter((item) => item.key === key) ?? []).map((item) => ({ ...item, value: item.value }))
    )

    return (
        <div className="mt-4 flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                <LemonButton size="small" loading={responseLoading} onClick={() => loadData('force_async')}>
                    Reload summary
                </LemonButton>
            </div>
            <h2 className="mb-0">Acquisition</h2>
            {responseError ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadData('force_async') }}>
                    Could not load acquisition metrics. Try again.
                </LemonBanner>
            ) : (
                <OverviewMetricCardGrid
                    items={items}
                    loading={responseLoading}
                    numSkeletons={3}
                    samplingRate={overview?.samplingRate}
                    preComputeStrategy={overview?.preComputeStrategy}
                    labelFromKey={labelFromKey}
                />
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
