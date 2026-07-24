import { MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'
import { MarketingAnalyticsCell } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/shared'
import { webAnalyticsDataTableQueryContext } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { Query } from '~/queries/Query/Query'
import {
    DataTableNode,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsDrillDownLevel,
    NodeKind,
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
    return (
        <div className="mt-4">
            <Query query={CHANNEL_SOURCE_BREAKDOWN} context={QUERY_CONTEXT} readOnly />
        </div>
    )
}
