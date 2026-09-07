import { useValues } from 'kea'

import { MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'
import { MarketingAnalyticsCell } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/shared'
import { webAnalyticsDataTableQueryContext } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { Query } from '~/queries/Query/Query'
import {
    DataTableNode,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumn } from '~/queries/types'

import { MarketingAnalyticsFreshness } from './MarketingAnalyticsFreshness'
import { MarketingAnalyticsNotReady } from './MarketingAnalyticsNotReady'

// Shared between the dataNodeLogic we bind to read freshness/not-ready and the DataTable that renders the
// results, so both use one logic instance (one load) rather than fetching the query twice.
const DATA_NODE_LOGIC_KEY = 'marketing-analytics-channel-source-breakdown'

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
// through to the raw JSON viewer. `dataNodeLogicKey` makes the table reuse the logic instance we bind
// below for freshness, so the query loads once.
const QUERY_CONTEXT: QueryContext = {
    ...webAnalyticsDataTableQueryContext,
    dataNodeLogicKey: DATA_NODE_LOGIC_KEY,
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
    // Bound to the same key the table uses, so we can read the precompute-only signals off the one
    // shared response: freshness for the badge, and not-ready to swap the table for a "computing" state.
    const { response, responseLoading } = useValues(
        dataNodeLogic({ key: DATA_NODE_LOGIC_KEY, query: CHANNEL_SOURCE_BREAKDOWN.source })
    )
    const marketingResponse = response as MarketingAnalyticsTableQueryResponse | null
    const notReady = !responseLoading && marketingResponse?.precomputeNotReady === true

    return (
        <div className="mt-4 flex flex-col gap-2">
            <div className="flex justify-end">
                <MarketingAnalyticsFreshness computedAt={marketingResponse?.dataComputedAt ?? null} />
            </div>
            {notReady ? (
                <MarketingAnalyticsNotReady />
            ) : (
                <Query query={CHANNEL_SOURCE_BREAKDOWN} context={QUERY_CONTEXT} readOnly />
            )}
        </div>
    )
}
