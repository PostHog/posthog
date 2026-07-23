import {
    IconAI,
    IconBrackets,
    IconCorrelationAnalysis,
    IconCursor,
    IconFlask,
    IconGraph,
    IconHogQL,
    IconLineGraph,
    IconLive,
    IconLlmAnalytics,
    IconPerson,
    IconPieChart,
    IconPiggyBank,
    IconTrends,
    IconVideoCamera,
    IconWarning,
} from '@posthog/icons'
import { LemonSelectOptions } from '@posthog/lemon-ui'

import {
    IconAction,
    IconBracketsChart,
    IconInsightCalendarHeatmap,
    IconInsightFunnels,
    IconInsightLifecycle,
    IconInsightRetention,
    IconInsightStickiness,
    IconInsightTrends,
    IconInsightUserPaths,
    IconTableChart,
} from 'lib/lemon-ui/icons'

import { NodeKind } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

export interface InsightTypeMetadata {
    name: string
    description?: string
    /** Override the description on the insight page tab, for additional info. */
    tooltipDescription?: string
    icon: React.ComponentType<any>
    inMenu: boolean
    tooltipDocLink?: string
}

export const QUERY_TYPES_METADATA: Record<NodeKind, InsightTypeMetadata> = {
    [NodeKind.CalendarHeatmapQuery]: {
        name: 'Calendar heatmap (BETA)',
        description: 'Visualize total or unique users broken down by day and hour.',
        icon: IconInsightCalendarHeatmap,
        inMenu: true,
        // tooltipDescription TODO: Add tooltip description
    },
    [NodeKind.TrendsQuery]: {
        name: 'Trends',
        description: 'Visualize and break down how actions or events vary over time.',
        icon: IconInsightTrends,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/trends/overview',
    },
    [NodeKind.FunnelsQuery]: {
        name: 'Funnel',
        description: 'Discover how many users complete or drop out of a sequence of actions.',
        icon: IconInsightFunnels,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/funnels',
    },
    [NodeKind.RetentionQuery]: {
        name: 'Retention',
        description: 'See how many users return on subsequent days after an initial action.',
        icon: IconInsightRetention,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/retention',
    },
    [NodeKind.PathsQuery]: {
        name: 'Paths',
        description: 'Trace the journeys users take within your product and where they drop off.',
        icon: IconInsightUserPaths,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/paths',
    },
    [NodeKind.StickinessQuery]: {
        name: 'Stickiness',
        description: 'See what keeps users coming back by viewing the interval between repeated actions.',
        icon: IconInsightStickiness,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/stickiness',
    },
    [NodeKind.LifecycleQuery]: {
        name: 'Lifecycle',
        description: 'Understand growth by breaking down new, resurrected, returning and dormant users.',
        tooltipDescription: 'Understand growth by breaking down new, resurrected, returning and dormant users.',
        icon: IconInsightLifecycle,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/lifecycle',
    },
    [NodeKind.FunnelCorrelationQuery]: {
        name: 'Funnel Correlation',
        description: 'See which events or properties correlate to a funnel result.',
        icon: IconCorrelationAnalysis,
        inMenu: false,
    },
    [NodeKind.EventsNode]: {
        name: 'Events',
        description: 'List and explore events.',
        icon: IconCursor,
        inMenu: true,
    },
    [NodeKind.ActionsNode]: {
        name: 'Actions',
        description: 'List and explore actions.',
        icon: IconAction,
        inMenu: true,
    },
    [NodeKind.DataWarehouseNode]: {
        name: 'Data Warehouse',
        description: 'List and explore data warehouse tables.',
        icon: IconTableChart,
        inMenu: true,
    },
    [NodeKind.FunnelsDataWarehouseNode]: {
        name: 'Funnels Data Warehouse',
        description: 'List and explore funnels data warehouse tables.',
        icon: IconTableChart,
        inMenu: true,
    },
    [NodeKind.LifecycleDataWarehouseNode]: {
        name: 'Lifecycle Data Warehouse',
        description: 'List and explore lifecycle data warehouse tables.',
        icon: IconTableChart,
        inMenu: true,
    },
    [NodeKind.GroupNode]: {
        name: 'Groups',
        description: 'List and explore grouped events.',
        icon: IconCursor,
        inMenu: false,
    },
    [NodeKind.EventsQuery]: {
        name: 'Events Query',
        description: 'List and explore events.',
        icon: IconCursor,
        inMenu: true,
    },
    [NodeKind.SessionBatchEventsQuery]: {
        name: 'Session Batch Events',
        description: 'Batch query for events from multiple sessions.',
        icon: IconCursor,
        inMenu: false,
    },
    [NodeKind.PersonsNode]: {
        name: 'Persons',
        description: 'List and explore your persons.',
        icon: IconPerson,
        inMenu: true,
    },
    [NodeKind.ActorsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions.',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.InsightActorsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions, derived from an insight.',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.ExperimentActorsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions, derived from an experiment.',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.InsightActorsQueryOptions]: {
        name: 'Persons',
        description: 'Options for InsightActorsQuery.',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.StickinessActorsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions, derived from an insight.',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.FunnelsActorsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions, derived from an insight.',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.FunnelCorrelationActorsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions, derived from an insight.',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.GroupsQuery]: {
        name: 'Groups',
        description: 'List and explore groups.',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.DataTableNode]: {
        name: 'Data table',
        description: 'Slice and dice your data in a table.',
        icon: IconTableChart,
        inMenu: true,
    },
    [NodeKind.DataVisualizationNode]: {
        name: 'SQL',
        description: 'Slice and dice your data in a table or chart.',
        icon: IconBracketsChart,
        inMenu: false,
    },
    [NodeKind.SavedInsightNode]: {
        name: 'Insight visualization by short id',
        description: 'View your insights.',
        icon: IconGraph,
        inMenu: true,
    },
    [NodeKind.InsightVizNode]: {
        name: 'Insight visualization',
        description: 'View your insights.',
        icon: IconGraph,
        inMenu: true,
    },
    [NodeKind.SessionsTimelineQuery]: {
        name: 'Sessions',
        description: 'Sessions timeline query.',
        icon: IconTrends,
        inMenu: true,
    },
    [NodeKind.HogQLQuery]: {
        name: 'SQL',
        description: 'Direct SQL query.',
        icon: IconBracketsChart,
        inMenu: true,
    },
    [NodeKind.HogQLMetadata]: {
        name: 'SQL Metadata',
        description: 'Metadata for a SQL query.',
        icon: IconBracketsChart,
        inMenu: true,
    },
    [NodeKind.HogQLAutocomplete]: {
        name: 'SQL Autocomplete',
        description: 'Autocomplete for the SQL query editor.',
        icon: IconBracketsChart,
        inMenu: false,
    },
    [NodeKind.DatabaseSchemaQuery]: {
        name: 'Database Schema',
        description: 'Introspect the PostHog database schema.',
        icon: IconBracketsChart,
        inMenu: true,
    },
    [NodeKind.RevenueAnalyticsMetricsQuery]: {
        name: 'Revenue Analytics Metrics',
        description: 'View revenue analytics customer, subscription count, ARPU, and LTV.',
        icon: IconPiggyBank,
        inMenu: true,
    },
    [NodeKind.RevenueAnalyticsOverviewQuery]: {
        name: 'Revenue Analytics Overview',
        description: 'View revenue analytics overview.',
        icon: IconPiggyBank,
        inMenu: true,
    },
    [NodeKind.RevenueAnalyticsGrossRevenueQuery]: {
        name: 'Revenue Analytics Gross Revenue',
        description: 'View gross revenue analytics.',
        icon: IconPiggyBank,
        inMenu: true,
    },
    [NodeKind.RevenueAnalyticsMRRQuery]: {
        name: 'Revenue Analytics MRR',
        description: 'View MRR revenue analytics.',
        icon: IconPiggyBank,
        inMenu: true,
    },
    [NodeKind.RevenueAnalyticsTopCustomersQuery]: {
        name: 'Revenue Analytics Top Customers',
        description: 'View revenue analytics top customers.',
        icon: IconPiggyBank,
        inMenu: true,
    },
    [NodeKind.WebOverviewQuery]: {
        name: 'Overview Stats',
        description: 'View overview stats for a website.',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.WebStatsTableQuery]: {
        name: 'Web Table',
        description: 'A table of results from web analytics, with a breakdown.',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.WebGoalsQuery]: {
        name: 'Goals',
        description: 'View goal conversions.',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.WebExternalClicksTableQuery]: {
        name: 'External click urls',
        description: 'View clicks on external links.',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.WebVitalsQuery]: {
        name: 'Web vitals',
        description: 'View web vitals.',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.WebVitalsPathBreakdownQuery]: {
        name: 'Web vitals path breakdown',
        description: 'View web vitals broken down by path.',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.WebPageURLSearchQuery]: {
        name: 'Web Page URL Search',
        description: 'Search and analyze web page URLs.',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.HogQuery]: {
        name: 'Hog',
        description: 'Hog query.',
        icon: IconHogQL,
        inMenu: true,
    },
    [NodeKind.SessionAttributionExplorerQuery]: {
        name: 'Session Attribution',
        description: 'Session Attribution Explorer.',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.SessionsQuery]: {
        name: 'Sessions',
        description: 'List and explore sessions.',
        icon: IconTableChart,
        inMenu: false,
    },
    [NodeKind.RevenueExampleEventsQuery]: {
        name: 'Revenue Example Events',
        description: 'Revenue Example Events Query.',
        icon: IconTableChart,
        inMenu: true,
    },
    [NodeKind.RevenueExampleDataWarehouseTablesQuery]: {
        name: 'Revenue Example Data Warehouse Tables',
        description: 'Revenue Example Data Warehouse Tables Query.',
        icon: IconTableChart,
        inMenu: true,
    },
    [NodeKind.ErrorTrackingQuery]: {
        name: 'Error Tracking',
        description: 'List and explore exception groups.',
        icon: IconWarning,
        inMenu: false,
    },
    [NodeKind.ErrorTrackingIssueCorrelationQuery]: {
        name: 'Error Tracking Correlation',
        description: 'Explore issues affecting other events.',
        icon: IconCorrelationAnalysis,
        inMenu: false,
    },
    [NodeKind.ErrorTrackingSimilarIssuesQuery]: {
        name: 'Error Tracking Similar Issues',
        description: 'Explore issues similar to the selected one.',
        icon: IconWarning,
        inMenu: false,
    },
    [NodeKind.ErrorTrackingBreakdownsQuery]: {
        name: 'Error Tracking Breakdowns',
        description: 'Break down error tracking issues by properties.',
        icon: IconWarning,
        inMenu: false,
    },
    [NodeKind.RecordingsQuery]: {
        name: 'Session Recordings',
        description: 'View available recordings.',
        icon: IconVideoCamera,
        inMenu: false,
    },
    [NodeKind.ExperimentQuery]: {
        name: 'Experiment Result',
        description: 'View experiment result.',
        icon: IconFlask,
        inMenu: false,
    },
    [NodeKind.ExperimentExposureQuery]: {
        name: 'Experiment Exposure',
        description: 'View experiment exposure.',
        icon: IconFlask,
        inMenu: false,
    },
    [NodeKind.ExperimentTrendsQuery]: {
        name: 'Experiment Trends Result',
        description: 'View experiment trend result.',
        icon: IconFlask,
        inMenu: false,
    },
    [NodeKind.ExperimentFunnelsQuery]: {
        name: 'Experiment Funnels Result',
        description: 'View experiment funnel result.',
        icon: IconFlask,
        inMenu: false,
    },
    [NodeKind.ExperimentEventExposureConfig]: {
        name: 'Experiment Event Exposure Config',
        description: 'Experiment event exposure configuration.',
        icon: IconFlask,
        inMenu: false,
    },
    [NodeKind.ExperimentMetric]: {
        name: 'Experiment Metric',
        description: 'Experiment metric configuration.',
        icon: IconFlask,
        inMenu: false,
    },
    [NodeKind.ExperimentDataWarehouseNode]: {
        name: 'Experiment Data Warehouse',
        description: 'Experiment data warehouse source configuration.',
        icon: IconFlask,
        inMenu: false,
    },
    [NodeKind.TeamTaxonomyQuery]: {
        name: 'Team Taxonomy',
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.EventTaxonomyQuery]: {
        name: 'Event Taxonomy',
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.SuggestedQuestionsQuery]: {
        name: 'AI Suggested Questions',
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.ActorsPropertyTaxonomyQuery]: {
        name: 'Actor Property Taxonomy',
        description: "View the taxonomy of the actor's property.",
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.TracesQuery]: {
        name: 'AI observability traces',
        icon: IconLlmAnalytics,
        inMenu: false,
    },
    [NodeKind.SessionQuery]: {
        name: 'AI observability session',
        icon: IconLlmAnalytics,
        inMenu: false,
    },
    [NodeKind.TraceNeighborsQuery]: {
        name: 'AI observability trace neighbors',
        icon: IconLlmAnalytics,
        inMenu: false,
    },
    [NodeKind.TraceQuery]: {
        name: 'AI observability trace',
        icon: IconLlmAnalytics,
        inMenu: false,
    },
    [NodeKind.DocumentSimilarityQuery]: {
        name: 'Document Similarity',
        description: 'Find documents similar to a given query.',
        icon: IconAI,
        inMenu: false,
    },
    [NodeKind.VectorSearchQuery]: {
        name: 'Vector Search',
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.LogsQuery]: {
        name: 'Logs',
        icon: IconLive,
        inMenu: false,
    },
    [NodeKind.LogAttributesQuery]: {
        name: 'LogAttributes',
        icon: IconLive,
        inMenu: false,
    },
    [NodeKind.LogValuesQuery]: {
        name: 'LogValues',
        icon: IconLive,
        inMenu: false,
    },
    [NodeKind.MetricsQuery]: {
        name: 'Metrics',
        description: 'Chart a service metric over time',
        icon: IconLive,
        inMenu: false,
    },
    [NodeKind.TraceSpansQuery]: {
        name: 'Trace Spans',
        icon: IconLive,
        inMenu: false,
    },
    [NodeKind.TraceSpansAggregationQuery]: {
        name: 'Trace Spans Aggregation',
        icon: IconLive,
        inMenu: false,
    },
    [NodeKind.TraceSpansTreeQuery]: {
        name: 'Trace Spans Tree',
        icon: IconLive,
        inMenu: false,
    },
    [NodeKind.TraceSpansAttributeBreakdownQuery]: {
        name: 'Trace Spans Attribute Breakdown',
        icon: IconLive,
        inMenu: false,
    },
    [NodeKind.TraceSpansSymbolStatsQuery]: {
        name: 'Trace Spans Symbol Stats',
        icon: IconLive,
        inMenu: false,
    },
    [NodeKind.WebAnalyticsExternalSummaryQuery]: {
        name: 'Web Analytics External Summary',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MarketingAnalyticsTableQuery]: {
        name: 'Marketing Analytics Table',
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.MarketingAnalyticsAggregatedQuery]: {
        name: 'Marketing Analytics Aggregated',
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.NonIntegratedConversionsTableQuery]: {
        name: 'Non-Integrated Conversions Table',
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.UsageMetricsQuery]: {
        name: 'Usage Metrics',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.AccountsQuery]: {
        name: 'Accounts',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.EndpointsUsageOverviewQuery]: {
        name: 'Endpoints usage overview',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.EndpointsUsageTableQuery]: {
        name: 'Endpoints usage table',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.EndpointsUsageTrendsQuery]: {
        name: 'Endpoints usage trends',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.PropertyValuesQuery]: {
        name: 'Property values',
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.WebNotableChangesQuery]: {
        name: 'Notable changes',
        description: 'View notable changes in web analytics metrics.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPHarnessBreakdownQuery]: {
        name: 'MCP harness breakdown',
        description: 'MCP tool-call activity grouped by client harness.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolSampleIntentsQuery]: {
        name: 'MCP tool sample intents',
        description: 'Recent sampled intents for a single MCP tool.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolNeighborsQuery]: {
        name: 'MCP tool neighbors',
        description: 'Tools called adjacent to a single MCP tool within a conversation.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolStatsQuery]: {
        name: 'MCP tool stats',
        description: 'Summary stats for a single MCP tool.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolDailyStatsQuery]: {
        name: 'MCP tool daily stats',
        description: 'Per-day activity for a single MCP tool.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolDescriptionsQuery]: {
        name: 'MCP tool descriptions',
        description: 'Reported descriptions for a single MCP tool.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolTopUsersQuery]: {
        name: 'MCP tool top users',
        description: 'Top users of a single MCP tool.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolFailuresQuery]: {
        name: 'MCP tool failures',
        description: 'Recurring exception messages for a single MCP tool.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolFailureOccurrencesQuery]: {
        name: 'MCP tool failure occurrences',
        description: 'Individual errored calls within one failure bucket of an MCP tool.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolQualityRowsQuery]: {
        name: 'MCP tool quality rows',
        description: 'Per-tool quality metrics for the Tool quality tab.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolQualityDailyStatsQuery]: {
        name: 'MCP tool quality daily stats',
        description: 'Interval-bucketed activity series for the Tool quality tab.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolCategoryCountsQuery]: {
        name: 'MCP tool category counts',
        description: 'Per-category call counts for the Tool quality tab.',
        icon: IconPieChart,
        inMenu: false,
    },
    [NodeKind.MCPToolCategoriesQuery]: {
        name: 'MCP tool categories',
        description: 'Distinct tool categories for the Tool quality scope selector.',
        icon: IconPieChart,
        inMenu: false,
    },
}

export const INSIGHT_TYPES_METADATA: Record<InsightType, InsightTypeMetadata> = {
    [InsightType.TRENDS]: QUERY_TYPES_METADATA[NodeKind.TrendsQuery],
    [InsightType.FUNNELS]: QUERY_TYPES_METADATA[NodeKind.FunnelsQuery],
    [InsightType.RETENTION]: QUERY_TYPES_METADATA[NodeKind.RetentionQuery],
    [InsightType.PATHS]: QUERY_TYPES_METADATA[NodeKind.PathsQuery],
    [InsightType.STICKINESS]: QUERY_TYPES_METADATA[NodeKind.StickinessQuery],
    [InsightType.LIFECYCLE]: QUERY_TYPES_METADATA[NodeKind.LifecycleQuery],
    [InsightType.SQL]: {
        name: 'SQL',
        description: 'Use SQL to query your data.',
        icon: IconBracketsChart,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/data-warehouse/sql',
    },
    [InsightType.JSON]: {
        name: 'Custom',
        description: 'Save components powered by our JSON query language.',
        icon: IconBrackets,
        inMenu: true,
    },
    [InsightType.HOG]: {
        name: 'Hog',
        description: 'Use Hog to query your data.',
        icon: IconHogQL,
        inMenu: false,
    },
    [InsightType.WEB_ANALYTICS]: {
        name: 'Web Analytics',
        description: 'Web analytics insights from your website data.',
        icon: IconLineGraph,
        inMenu: false,
    },
}

export const INSIGHT_TYPE_OPTIONS: LemonSelectOptions<string> = [
    { value: 'All types', label: 'All types' },
    ...Object.entries(INSIGHT_TYPES_METADATA)
        .filter(([, meta]) => meta.inMenu !== false)
        .map(([value, meta]) => ({
            value,
            label: meta.name,
            icon: meta.icon ? <meta.icon /> : undefined,
        })),
]
