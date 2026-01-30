import './SavedInsights.scss'

import { useActions, useValues } from 'kea'

import {
    IconAI,
    IconBrackets,
    IconChevronDown,
    IconCorrelationAnalysis,
    IconCursor,
    IconFilter,
    IconFlask,
    IconFunnels,
    IconGraph,
    IconHogQL,
    IconLifecycle,
    IconLineGraph,
    IconLive,
    IconLlmAnalytics,
    IconPerson,
    IconPieChart,
    IconPiggyBank,
    IconPlusSmall,
    IconRetention,
    IconRetentionHeatmap,
    IconStar,
    IconStarFilled,
    IconStickiness,
    IconTrends,
    IconUserPaths,
    IconVideoCamera,
    IconWarning,
} from '@posthog/icons'
import { LemonSelectOption, LemonSelectOptionLeaf, LemonSelectOptions } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { Alerts } from 'lib/components/Alerts/views/Alerts'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { tagSelectLogic } from 'lib/components/tagSelectLogic'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { IconAction, IconTableChart } from 'lib/lemon-ui/icons'
import { dateMapping, fullName, isNonEmptyObject } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { deleteInsightWithUndo } from 'lib/utils/deleteWithUndo'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { membersLogic } from 'scenes/organization/membersLogic'
import { projectLogic } from 'scenes/projectLogic'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { NewInsightShortcuts, OverlayForNewInsightMenu } from 'scenes/saved-insights/newInsightsMenu'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { isNodeWithSource } from '~/queries/utils'
import {
    AccessControlLevel,
    AccessControlResourceType,
    ActivityScope,
    InsightType,
    QueryBasedInsightModel,
    SavedInsightsTabs,
} from '~/types'

import { ReloadInsight } from './ReloadInsight'
import { savedInsightsLogic } from './savedInsightsLogic'

interface NewInsightButtonProps {
    dataAttr: string
}

export interface InsightTypeMetadata {
    name: string
    description?: string
    /** Override the description on the insight page tab, for additional info. */
    tooltipDescription?: string
    icon: (props?: any) => JSX.Element | null
    inMenu: boolean
    tooltipDocLink?: string
}

export const QUERY_TYPES_METADATA: Record<NodeKind, InsightTypeMetadata> = {
    [NodeKind.CalendarHeatmapQuery]: {
        name: 'Calendar heatmap (BETA)',
        description: 'Visualize total or unique users broken down by day and hour.',
        icon: IconRetentionHeatmap,
        inMenu: true,
        // tooltipDescription TODO: Add tooltip description
    },
    [NodeKind.TrendsQuery]: {
        name: 'Trends',
        description: 'Visualize and break down how actions or events vary over time.',
        icon: IconTrends,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/trends/overview',
    },
    [NodeKind.FunnelsQuery]: {
        name: 'Funnel',
        description: 'Discover how many users complete or drop out of a sequence of actions.',
        icon: IconFunnels,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/funnels',
    },
    [NodeKind.RetentionQuery]: {
        name: 'Retention',
        description: 'See how many users return on subsequent days after an initial action.',
        icon: IconRetention,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/retention',
    },
    [NodeKind.PathsQuery]: {
        name: 'Paths',
        description: 'Trace the journeys users take within your product and where they drop off.',
        icon: IconUserPaths,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/paths',
    },
    [NodeKind.StickinessQuery]: {
        name: 'Stickiness',
        description: 'See what keeps users coming back by viewing the interval between repeated actions.',
        icon: IconStickiness,
        inMenu: true,
        tooltipDocLink: 'https://posthog.com/docs/product-analytics/stickiness',
    },
    [NodeKind.LifecycleQuery]: {
        name: 'Lifecycle',
        description: 'Understand growth by breaking down new, resurrected, returning and dormant users.',
        tooltipDescription: 'Understand growth by breaking down new, resurrected, returning and dormant users.',
        icon: IconLifecycle,
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
        icon: IconTableChart,
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
        icon: IconBrackets,
        inMenu: true,
    },
    [NodeKind.HogQLASTQuery]: {
        name: 'SQL AST',
        description: 'Direct SQL AST query.',
        icon: IconBrackets,
        inMenu: false,
    },
    [NodeKind.HogQLMetadata]: {
        name: 'SQL Metadata',
        description: 'Metadata for a SQL query.',
        icon: IconHogQL,
        inMenu: true,
    },
    [NodeKind.HogQLAutocomplete]: {
        name: 'SQL Autocomplete',
        description: 'Autocomplete for the SQL query editor.',
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.DatabaseSchemaQuery]: {
        name: 'Database Schema',
        description: 'Introspect the PostHog database schema.',
        icon: IconHogQL,
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
    [NodeKind.WebTrendsQuery]: {
        name: 'Web Trends',
        description: 'Analyze web trends and patterns over time.',
        icon: IconTrends,
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
        name: 'LLM Analytics Traces',
        icon: IconLlmAnalytics,
        inMenu: false,
    },
    [NodeKind.TraceNeighborsQuery]: {
        name: 'LLM Analytics Trace Neighbors',
        icon: IconLlmAnalytics,
        inMenu: false,
    },
    [NodeKind.TraceQuery]: {
        name: 'LLM Analytics Trace',
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
        icon: IconHogQL,
        inMenu: true,
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
        inMenu: true,
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
    ...Object.entries(INSIGHT_TYPES_METADATA).map(([value, meta]) => ({
        value,
        label: meta.name,
        icon: meta.icon ? <meta.icon /> : undefined,
    })),
]

export const scene: SceneExport = {
    component: SavedInsights,
    logic: savedInsightsLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}

export function InsightIcon({
    insight,
    className,
}: {
    insight: QueryBasedInsightModel
    className?: string
}): JSX.Element | null {
    let Icon: (props?: any) => JSX.Element | null = () => null

    if ('query' in insight && isNonEmptyObject(insight.query)) {
        const insightType = isNodeWithSource(insight.query) ? insight.query.source.kind : insight.query.kind
        const insightMetadata = QUERY_TYPES_METADATA[insightType]
        Icon = insightMetadata && insightMetadata.icon
    }

    return Icon ? <Icon className={className} /> : null
}

export function NewInsightButton({ dataAttr }: NewInsightButtonProps): JSX.Element {
    const useInsightOptionsPage = useFeatureFlag('INSIGHT_OPTIONS_PAGE', 'test')

    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.Insight}
            minAccessLevel={AccessControlLevel.Editor}
        >
            <AppShortcut
                name="NewInsight"
                keybind={[keyBinds.new]}
                intent="New insight"
                interaction="click"
                scope={Scene.SavedInsights}
                priority={100}
            >
                <LemonButton
                    type="primary"
                    to={useInsightOptionsPage ? urls.insightOptions() : urls.insightNew()}
                    sideAction={{
                        dropdown: {
                            placement: 'bottom-end',
                            className: 'new-insight-overlay',
                            actionable: true,
                            overlay: <OverlayForNewInsightMenu dataAttr={dataAttr} />,
                        },
                        'data-attr': 'saved-insights-new-insight-dropdown',
                    }}
                    data-attr="saved-insights-new-insight-button"
                    size="small"
                    icon={<IconPlusSmall />}
                    tooltip="New insight"
                >
                    New
                </LemonButton>
            </AppShortcut>
        </AccessControlAction>
    )
}

export function SavedInsights(): JSX.Element {
    const { loadInsights, updateFavoritedInsight, renameInsight, duplicateInsight, setSavedInsightsFilters } =
        useActions(savedInsightsLogic)
    const { insights, insightsLoading, filters, sorting, pagination, alertModalId, usingFilters } =
        useValues(savedInsightsLogic)

    const { currentProjectId } = useValues(projectLogic)
    const summarizeInsight = useSummarizeInsight()

    const { filteredTags, search: tagSearch } = useValues(tagSelectLogic)
    const { setSearch: setTagSearch } = useActions(tagSelectLogic)

    const { meFirstMembers, filteredMembers, search: memberSearch } = useValues(membersLogic)
    const { setSearch: setMemberSearch, ensureAllMembersLoaded } = useActions(membersLogic)

    const { tab } = filters

    const handleTagToggle = (tag: string): void => {
        const selected = new Set(filters.tags || [])
        if (selected.has(tag)) {
            selected.delete(tag)
        } else {
            selected.add(tag)
        }
        setSavedInsightsFilters({ tags: Array.from(selected) })
    }

    const handleMemberToggle = (userId: number): void => {
        const currentUsers = filters.createdBy !== 'All users' ? (filters.createdBy as number[]) : []
        const selected = new Set(currentUsers)
        if (selected.has(userId)) {
            selected.delete(userId)
        } else {
            selected.add(userId)
        }
        const newValue = Array.from(selected)
        setSavedInsightsFilters({ createdBy: newValue.length > 0 ? newValue : 'All users' })
    }

    const createDateFilterOverlay = (
        dateFrom: string | dayjs.Dayjs | undefined | null,
        dateTo: string | dayjs.Dayjs | undefined | null,
        onChange: (fromDate: string | null, toDate: string | null) => void
    ): JSX.Element => {
        const relevantDateOptions = dateMapping.filter((dm) => dm.key !== 'Custom' && dm.key !== 'All time')
        const isActive = (option: (typeof dateMapping)[0]): boolean =>
            (dateFrom ?? null) === (option.values[0] ?? null) && (dateTo ?? null) === (option.values[1] ?? null)

        return (
            <div className="deprecated-space-y-px">
                {relevantDateOptions.map((option) => (
                    <LemonButton
                        key={option.key}
                        onClick={() => onChange(option.values[0] || null, option.values[1] || null)}
                        active={isActive(option)}
                        fullWidth
                    >
                        {option.key}
                    </LemonButton>
                ))}
                {dateFrom && dateFrom !== 'all' && (
                    <>
                        <div className="my-1 border-t" />
                        <LemonButton fullWidth onClick={() => onChange(null, null)} type="tertiary">
                            Clear filter
                        </LemonButton>
                    </>
                )}
            </div>
        )
    }

    const columns: LemonTableColumns<QueryBasedInsightModel> = [
        {
            key: 'id',
            width: 32,
            render: function renderType(_, insight) {
                return <InsightIcon insight={insight} className="text-secondary text-2xl" />
            },
            more: (
                <div className="deprecated-space-y-px">
                    {(INSIGHT_TYPE_OPTIONS as LemonSelectOption<string>[]).map((option) => (
                        <LemonButton
                            key={(option as LemonSelectOptionLeaf<string>).value}
                            onClick={() =>
                                setSavedInsightsFilters({
                                    insightType: (option as LemonSelectOptionLeaf<string>).value,
                                })
                            }
                            active={filters.insightType === (option as LemonSelectOptionLeaf<string>).value}
                            icon={option.icon}
                            fullWidth
                        >
                            {option.label}
                        </LemonButton>
                    ))}
                    {filters.insightType && filters.insightType !== 'All types' && (
                        <>
                            <div className="my-1 border-t" />
                            <LemonButton
                                fullWidth
                                onClick={() => setSavedInsightsFilters({ insightType: 'All types' })}
                                type="tertiary"
                            >
                                Clear filter
                            </LemonButton>
                        </>
                    )}
                </div>
            ),
            moreIcon: <IconFilter />,
            moreFilterCount: filters.insightType && filters.insightType !== 'All types' ? 1 : 0,
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: string, insight) {
                return (
                    <>
                        <LemonTableLink
                            to={urls.insightView(insight.short_id)}
                            title={
                                <>
                                    {name || <i>{summarizeInsight(insight.query)}</i>}

                                    <AccessControlAction
                                        resourceType={AccessControlResourceType.Insight}
                                        minAccessLevel={AccessControlLevel.Editor}
                                        userAccessLevel={insight.user_access_level}
                                    >
                                        <LemonButton
                                            className="ml-1"
                                            size="xsmall"
                                            onClick={(e) => {
                                                e.preventDefault()
                                                updateFavoritedInsight(insight, !insight.favorited)
                                            }}
                                            icon={
                                                insight.favorited ? (
                                                    <IconStarFilled className="text-warning" />
                                                ) : (
                                                    <IconStar className="text-secondary" />
                                                )
                                            }
                                            tooltip={`${insight.favorited ? 'Remove from' : 'Add to'} favorite insights`}
                                        />
                                    </AccessControlAction>
                                </>
                            }
                            description={insight.description}
                        />
                    </>
                )
            },
            sorter: (a, b) => (a.name || summarizeInsight(a.query)).localeCompare(b.name || summarizeInsight(b.query)),
        },
        {
            title: 'Tags',
            dataIndex: 'tags' as keyof QueryBasedInsightModel,
            key: 'tags',
            render: function renderTags(tags: string[]) {
                return <ObjectTags tags={tags} staticOnly />
            },
            more: (
                <div className="max-w-100 deprecated-space-y-2">
                    <LemonInput
                        type="search"
                        placeholder="Search tags"
                        autoFocus
                        value={tagSearch}
                        onChange={setTagSearch}
                        fullWidth
                        className="max-w-full"
                    />
                    <ul className="deprecated-space-y-px">
                        {filteredTags.map((tag: string) => (
                            <li key={tag}>
                                <LemonButton
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    onClick={() => handleTagToggle(tag)}
                                >
                                    <span className="flex items-center justify-between gap-2 flex-1">
                                        <span className="flex items-center gap-2 max-w-full">
                                            <input
                                                type="checkbox"
                                                className="cursor-pointer"
                                                checked={filters.tags?.includes(tag) || false}
                                                readOnly
                                            />
                                            <span>{tag}</span>
                                        </span>
                                    </span>
                                </LemonButton>
                            </li>
                        ))}
                        {filteredTags.length === 0 ? (
                            <div className="p-2 text-secondary italic truncate border-t">
                                {tagSearch ? <span>No matching tags</span> : <span>No tags</span>}
                            </div>
                        ) : null}
                        {(filters.tags?.length || 0) > 0 && (
                            <>
                                <div className="my-1 border-t" />
                                <li>
                                    <LemonButton
                                        fullWidth
                                        role="menuitem"
                                        size="small"
                                        onClick={() => setSavedInsightsFilters({ tags: [] })}
                                        type="tertiary"
                                    >
                                        Clear selection
                                    </LemonButton>
                                </li>
                            </>
                        )}
                    </ul>
                </div>
            ),
            moreIcon: <IconChevronDown />,
            moreFilterCount: filters.tags?.length || 0,
        },
        ...(tab === SavedInsightsTabs.Yours
            ? []
            : [
                  {
                      title: 'Created by',
                      dataIndex: 'created_by' as keyof QueryBasedInsightModel,
                      render: function Render(_: any, item: QueryBasedInsightModel) {
                          const { created_by } = item
                          return (
                              <div className="flex flex-row items-center flex-nowrap">
                                  {created_by && <ProfilePicture user={created_by} size="md" showName />}
                              </div>
                          )
                      },
                      sorter: (a, b) =>
                          (a.created_by?.first_name || a.created_by?.email || '').localeCompare(
                              b.created_by?.first_name || b.created_by?.email || ''
                          ),
                      more: (
                          <div className="max-w-100 deprecated-space-y-2" onClick={() => ensureAllMembersLoaded()}>
                              <LemonInput
                                  type="search"
                                  placeholder="Search"
                                  autoFocus
                                  value={memberSearch}
                                  onChange={setMemberSearch}
                                  fullWidth
                              />
                              <ul className="deprecated-space-y-px">
                                  {filteredMembers.map((member) => (
                                      <li key={member.user.uuid}>
                                          <LemonButton
                                              fullWidth
                                              role="menuitem"
                                              size="small"
                                              icon={<ProfilePicture size="md" user={member.user} />}
                                              onClick={() => handleMemberToggle(member.user.id)}
                                          >
                                              <span className="flex items-center justify-between gap-2 flex-1">
                                                  <span className="flex items-center gap-2 max-w-full">
                                                      <input
                                                          type="checkbox"
                                                          className="cursor-pointer"
                                                          checked={
                                                              filters.createdBy !== 'All users' &&
                                                              (filters.createdBy as number[]).includes(member.user.id)
                                                          }
                                                          readOnly
                                                      />
                                                      <span>{fullName(member.user)}</span>
                                                  </span>
                                                  <span className="text-secondary">
                                                      {meFirstMembers[0] === member && `(you)`}
                                                  </span>
                                              </span>
                                          </LemonButton>
                                      </li>
                                  ))}
                                  {filteredMembers.length === 0 ? (
                                      <div className="p-2 text-secondary italic truncate border-t">
                                          {memberSearch ? <span>No matches</span> : <span>No users</span>}
                                      </div>
                                  ) : null}
                                  {filters.createdBy !== 'All users' && (filters.createdBy as number[]).length > 0 && (
                                      <>
                                          <div className="my-1 border-t" />
                                          <li>
                                              <LemonButton
                                                  fullWidth
                                                  role="menuitem"
                                                  size="small"
                                                  onClick={() => setSavedInsightsFilters({ createdBy: 'All users' })}
                                                  type="tertiary"
                                              >
                                                  Clear selection
                                              </LemonButton>
                                          </li>
                                      </>
                                  )}
                              </ul>
                          </div>
                      ),
                      moreIcon: <IconChevronDown />,
                      moreFilterCount: filters.createdBy !== 'All users' ? (filters.createdBy as number[]).length : 0,
                  } as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>,
              ]),
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: function RenderCreated(created_at: string) {
                return created_at ? (
                    <div className="whitespace-nowrap text-right">
                        <TZLabel time={created_at} />
                    </div>
                ) : (
                    <span className="text-secondary">—</span>
                )
            },
            align: 'right',
            sorter: (a, b) => dayjs(a.created_at || 0).diff(b.created_at || 0),
            more: createDateFilterOverlay(filters.createdDateFrom, filters.createdDateTo, (fromDate, toDate) =>
                setSavedInsightsFilters({ createdDateFrom: fromDate, createdDateTo: toDate })
            ),
            moreIcon: <IconChevronDown />,
            moreFilterCount: filters.createdDateFrom && filters.createdDateFrom !== 'all' ? 1 : 0,
        } as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>,
        {
            title: 'Last modified',
            sorter: true,
            dataIndex: 'last_modified_at',
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div className="whitespace-nowrap">{last_modified_at && <TZLabel time={last_modified_at} />}</div>
                )
            },
            more: createDateFilterOverlay(filters.dateFrom, filters.dateTo, (fromDate, toDate) =>
                setSavedInsightsFilters({ dateFrom: fromDate, dateTo: toDate })
            ),
            moreIcon: <IconChevronDown />,
            moreFilterCount: filters.dateFrom && filters.dateFrom !== 'all' ? 1 : 0,
        },
        {
            title: 'Last viewed',
            sorter: true,
            dataIndex: 'last_viewed_at',
            render: function renderLastViewed(last_viewed_at: string | null) {
                return (
                    <div className="whitespace-nowrap">
                        {last_viewed_at ? <TZLabel time={last_viewed_at} /> : <span className="text-muted">Never</span>}
                    </div>
                )
            },
            more: createDateFilterOverlay(filters.lastViewedDateFrom, filters.lastViewedDateTo, (fromDate, toDate) =>
                setSavedInsightsFilters({ lastViewedDateFrom: fromDate, lastViewedDateTo: toDate })
            ),
            moreIcon: <IconChevronDown />,
            moreFilterCount: filters.lastViewedDateFrom && filters.lastViewedDateFrom !== 'all' ? 1 : 0,
        },
        {
            width: 0,
            render: function Render(_, insight) {
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton to={urls.insightView(insight.short_id)} fullWidth>
                                    View
                                </LemonButton>

                                <LemonDivider />

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Insight}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={insight.user_access_level}
                                >
                                    <LemonButton to={urls.insightEdit(insight.short_id)} fullWidth>
                                        Edit
                                    </LemonButton>
                                </AccessControlAction>

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Insight}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={insight.user_access_level}
                                >
                                    <LemonButton
                                        onClick={() => renameInsight(insight)}
                                        data-attr={`insight-item-${insight.short_id}-dropdown-rename`}
                                        fullWidth
                                    >
                                        Rename
                                    </LemonButton>
                                </AccessControlAction>

                                <LemonButton
                                    onClick={() => duplicateInsight(insight)}
                                    data-attr="duplicate-insight-from-list-view"
                                    fullWidth
                                >
                                    Duplicate
                                </LemonButton>

                                <LemonDivider />

                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Insight}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={insight.user_access_level}
                                >
                                    <LemonButton
                                        status="danger"
                                        onClick={() =>
                                            void deleteInsightWithUndo({
                                                object: insight,
                                                endpoint: `projects/${currentProjectId}/insights`,
                                                callback: loadInsights,
                                            })
                                        }
                                        data-attr={`insight-item-${insight.short_id}-dropdown-remove`}
                                        fullWidth
                                    >
                                        Delete insight
                                    </LemonButton>
                                </AccessControlAction>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <SceneContent className={cn('saved-insights')}>
            <NewInsightShortcuts />
            <SceneTitleSection
                name={sceneConfigurations[Scene.SavedInsights].name}
                description={sceneConfigurations[Scene.SavedInsights].description}
                resourceType={{
                    type: sceneConfigurations[Scene.SavedInsights].iconType || 'default_icon_type',
                }}
                actions={<NewInsightButton dataAttr="saved-insights-create-new-insight" />}
            />
            <LemonTabs
                activeKey={tab}
                onChange={(tab) => setSavedInsightsFilters({ tab })}
                tabs={[
                    { key: SavedInsightsTabs.All, label: 'All insights' },
                    { key: SavedInsightsTabs.Yours, label: 'My insights' },
                    { key: SavedInsightsTabs.Favorites, label: 'Favorites' },
                    { key: SavedInsightsTabs.History, label: 'History' },
                    {
                        key: SavedInsightsTabs.Alerts,
                        label: <div className="flex items-center gap-2">Alerts</div>,
                    },
                ]}
                sceneInset
            />

            {tab === SavedInsightsTabs.History ? (
                <ActivityLog scope={ActivityScope.INSIGHT} />
            ) : tab === SavedInsightsTabs.Alerts ? (
                <Alerts alertId={alertModalId} />
            ) : (
                <>
                    <SavedInsightsFilters filters={filters} setFilters={setSavedInsightsFilters} />

                    <ReloadInsight />
                    <LemonTable
                        loading={insightsLoading}
                        columns={columns}
                        dataSource={insights.results}
                        pagination={pagination}
                        noSortingCancellation
                        sorting={sorting}
                        onSort={(newSorting) =>
                            setSavedInsightsFilters({
                                order: newSorting
                                    ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                    : undefined,
                            })
                        }
                        rowKey="id"
                        loadingSkeletonRows={15}
                        nouns={['insight', 'insights']}
                        hideSortingIndicatorWhenInactive
                        emptyState={
                            !insightsLoading && insights.count < 1 ? (
                                <div className="py-8">
                                    <SavedInsightsEmptyState filters={filters} usingFilters={usingFilters} />
                                </div>
                            ) : undefined
                        }
                    />
                </>
            )}
        </SceneContent>
    )
}
