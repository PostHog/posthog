import './SavedInsights.scss'

import {
    IconBrackets,
    IconCorrelationAnalysis,
    IconCursor,
    IconFlask,
    IconFunnels,
    IconGraph,
    IconHogQL,
    IconLifecycle,
    IconMinusSmall,
    IconPerson,
    IconPieChart,
    IconPlusSmall,
    IconRetention,
    IconStickiness,
    IconTrends,
    IconUserPaths,
    IconVideoCamera,
    IconWarning,
} from '@posthog/icons'
import { LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { Alerts } from 'lib/components/Alerts/views/Alerts'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { IconAction, IconTableChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { isNonEmptyObject } from 'lib/utils'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { organizationLogic } from 'scenes/organizationLogic'
import { overlayForNewInsightMenu } from 'scenes/saved-insights/newInsightsMenu'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema'
import { isNodeWithSource } from '~/queries/utils'
import { ActivityScope, InsightType, QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { INSIGHTS_PER_PAGE, savedInsightsLogic } from './savedInsightsLogic'

interface NewInsightButtonProps {
    dataAttr: string
}

export interface InsightTypeMetadata {
    name: string
    description?: string
    icon: (props?: any) => JSX.Element | null
    inMenu: boolean
}

export const INSIGHT_TYPES_METADATA: Record<InsightType, InsightTypeMetadata> = {
    [InsightType.TRENDS]: {
        name: 'Trends',
        description: 'Visualize and break down how actions or events vary over time.',
        icon: IconTrends,
        inMenu: true,
    },
    [InsightType.FUNNELS]: {
        name: 'Funnel',
        description: 'Discover how many users complete or drop out of a sequence of actions.',
        icon: IconFunnels,
        inMenu: true,
    },
    [InsightType.RETENTION]: {
        name: 'Retention',
        description: 'See how many users return on subsequent days after an initial action.',
        icon: IconRetention,
        inMenu: true,
    },
    [InsightType.PATHS]: {
        name: 'Paths',
        description: 'Trace the journeys users take within your product and where they drop off.',
        icon: IconUserPaths,
        inMenu: true,
    },
    [InsightType.STICKINESS]: {
        name: 'Stickiness',
        description: 'See what keeps users coming back by viewing the interval between repeated actions.',
        icon: IconStickiness,
        inMenu: true,
    },
    [InsightType.LIFECYCLE]: {
        name: 'Lifecycle',
        description: 'Understand growth by breaking down new, resurrected, returning and dormant users.',
        icon: IconLifecycle,
        inMenu: true,
    },
    [InsightType.SQL]: {
        name: 'SQL',
        description: 'Use HogQL to query your data.',
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
}

export const QUERY_TYPES_METADATA: Record<NodeKind, InsightTypeMetadata> = {
    [NodeKind.TrendsQuery]: {
        name: 'Trends',
        description: 'Visualize and break down how actions or events vary over time',
        icon: IconTrends,
        inMenu: true,
    },
    [NodeKind.FunnelsQuery]: {
        name: 'Funnel',
        description: 'Discover how many users complete or drop out of a sequence of actions',
        icon: IconFunnels,
        inMenu: true,
    },
    [NodeKind.RetentionQuery]: {
        name: 'Retention',
        description: 'See how many users return on subsequent days after an initial action',
        icon: IconRetention,
        inMenu: true,
    },
    [NodeKind.PathsQuery]: {
        name: 'Paths',
        description: 'Trace the journeys users take within your product and where they drop off',
        icon: IconUserPaths,
        inMenu: true,
    },
    [NodeKind.StickinessQuery]: {
        name: 'Stickiness',
        description: 'See what keeps users coming back by viewing the interval between repeated actions',
        icon: IconStickiness,
        inMenu: true,
    },
    [NodeKind.LifecycleQuery]: {
        name: 'Lifecycle',
        description: 'Understand growth by breaking down new, resurrected, returning and dormant users',
        icon: IconLifecycle,
        inMenu: true,
    },
    [NodeKind.FunnelCorrelationQuery]: {
        name: 'Funnel Correlation',
        description: 'See which events or properties correlate to a funnel result',
        icon: IconCorrelationAnalysis,
        inMenu: false,
    },
    [NodeKind.EventsNode]: {
        name: 'Events',
        description: 'List and explore events',
        icon: IconCursor,
        inMenu: true,
    },
    [NodeKind.ActionsNode]: {
        name: 'Actions',
        description: 'List and explore actions',
        icon: IconAction,
        inMenu: true,
    },
    [NodeKind.DataWarehouseNode]: {
        name: 'Data Warehouse',
        description: 'List and explore data warehouse tables',
        icon: IconTableChart,
        inMenu: true,
    },
    [NodeKind.EventsQuery]: {
        name: 'Events Query',
        description: 'List and explore events',
        icon: IconCursor,
        inMenu: true,
    },
    [NodeKind.PersonsNode]: {
        name: 'Persons',
        description: 'List and explore your persons',
        icon: IconPerson,
        inMenu: true,
    },
    [NodeKind.ActorsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.InsightActorsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions, derived from an insight',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.InsightActorsQueryOptions]: {
        name: 'Persons',
        description: 'Options for InsightActorsQueryt',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.FunnelsActorsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions, derived from an insight',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.FunnelCorrelationActorsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions, derived from an insight',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.DataTableNode]: {
        name: 'Data table',
        description: 'Slice and dice your data in a table',
        icon: IconTableChart,
        inMenu: true,
    },
    [NodeKind.DataVisualizationNode]: {
        name: 'Data visualization',
        description: 'Slice and dice your data in a table or chart',
        icon: IconTableChart,
        inMenu: false,
    },
    [NodeKind.SavedInsightNode]: {
        name: 'Insight visualization by short id',
        description: 'View your insights',
        icon: IconGraph,
        inMenu: true,
    },
    [NodeKind.InsightVizNode]: {
        name: 'Insight visualization',
        description: 'View your insights',
        icon: IconGraph,
        inMenu: true,
    },
    [NodeKind.SessionsTimelineQuery]: {
        name: 'Sessions',
        description: 'Sessions timeline query',
        icon: IconTrends,
        inMenu: true,
    },
    [NodeKind.HogQLQuery]: {
        name: 'HogQL',
        description: 'Direct HogQL query',
        icon: IconBrackets,
        inMenu: true,
    },
    [NodeKind.HogQLMetadata]: {
        name: 'HogQL Metadata',
        description: 'Metadata for a HogQL query',
        icon: IconHogQL,
        inMenu: true,
    },
    [NodeKind.HogQLAutocomplete]: {
        name: 'HogQL Autocomplete',
        description: 'Autocomplete for the HogQL query editor',
        icon: IconHogQL,
        inMenu: false,
    },
    [NodeKind.DatabaseSchemaQuery]: {
        name: 'Database Schema',
        description: 'Introspect the PostHog database schema',
        icon: IconHogQL,
        inMenu: true,
    },
    [NodeKind.WebOverviewQuery]: {
        name: 'Overview Stats',
        description: 'View overview stats for a website',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.WebStatsTableQuery]: {
        name: 'Web Table',
        description: 'A table of results from web analytics, with a breakdown',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.WebGoalsQuery]: {
        name: 'Goals',
        description: 'View goal conversions',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.WebExternalClicksTableQuery]: {
        name: 'External click urls',
        description: 'View clicks on external links',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.HogQuery]: {
        name: 'Hog',
        description: 'Hog query',
        icon: IconHogQL,
        inMenu: true,
    },
    [NodeKind.SessionAttributionExplorerQuery]: {
        name: 'Session Attribution',
        description: 'Session Attribution Explorer',
        icon: IconPieChart,
        inMenu: true,
    },
    [NodeKind.ErrorTrackingQuery]: {
        name: 'Error Tracking',
        description: 'List and explore exception groups',
        icon: IconWarning,
        inMenu: false,
    },
    [NodeKind.RecordingsQuery]: {
        name: 'Session Recordings',
        description: 'View available recordings',
        icon: IconVideoCamera,
        inMenu: false,
    },
    [NodeKind.ExperimentTrendsQuery]: {
        name: 'Experiment Trends Result',
        description: 'View experiment trend result',
        icon: IconFlask,
        inMenu: false,
    },
    [NodeKind.ExperimentFunnelsQuery]: {
        name: 'Experiment Funnels Result',
        description: 'View experiment funnel result',
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
        description: 'View the taxonomy of the actor’s property.',
        icon: IconHogQL,
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
    component: AddSavedInsightsToDashboard,
    logic: savedInsightsLogic,
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
    return (
        <LemonButton
            type="primary"
            to={urls.insightNew()}
            sideAction={{
                dropdown: {
                    placement: 'bottom-end',
                    className: 'new-insight-overlay',
                    actionable: true,
                    overlay: overlayForNewInsightMenu(dataAttr),
                },
                'data-attr': 'saved-insights-new-insight-dropdown',
            }}
            data-attr="saved-insights-new-insight-button"
            size="small"
            icon={<IconPlusSmall />}
        >
            New insight
        </LemonButton>
    )
}

export function AddSavedInsightsToDashboard(): JSX.Element {
    const { setSavedInsightsFilters, addInsightToDashboard, removeInsightFromDashboard } =
        useActions(savedInsightsLogic)
    const { insights, count, insightsLoading, filters, sorting, pagination, alertModalId } =
        useValues(savedInsightsLogic)
    const { hasTagging } = useValues(organizationLogic)
    const { dashboard } = useValues(dashboardLogic)

    const summarizeInsight = useSummarizeInsight()

    const { tab, page } = filters

    const startCount = (page - 1) * INSIGHTS_PER_PAGE + 1
    const endCount = page * INSIGHTS_PER_PAGE < count ? page * INSIGHTS_PER_PAGE : count

    const columns: LemonTableColumns<QueryBasedInsightModel> = [
        {
            key: 'id',
            width: 32,
            render: function renderType(_, insight) {
                return <InsightIcon insight={insight} className="text-muted text-2xl" />
            },
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
                            title={<>{name || <i>{summarizeInsight(insight.query)}</i>}</>}
                            description={insight.description}
                        />
                    </>
                )
            },
        },
        ...(hasTagging
            ? [
                  {
                      title: 'Tags',
                      dataIndex: 'tags' as keyof QueryBasedInsightModel,
                      key: 'tags',
                      render: function renderTags(tags: string[]) {
                          return <ObjectTags tags={tags} staticOnly />
                      },
                  },
              ]
            : []),
        ...(tab === SavedInsightsTabs.Yours
            ? []
            : [
                  createdByColumn() as LemonTableColumn<
                      QueryBasedInsightModel,
                      keyof QueryBasedInsightModel | undefined
                  >,
              ]),
        createdAtColumn() as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>,
        {
            title: 'Last modified',
            sorter: true,
            dataIndex: 'last_modified_at',
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div className="whitespace-nowrap">{last_modified_at && <TZLabel time={last_modified_at} />}</div>
                )
            },
        },
        {
            width: 0,
            render: function Render(_, insight) {
                const isInDashboard = dashboard?.tiles.some((tile) => tile.insight?.id === insight.id)
                return isInDashboard ? (
                    <LemonButton
                        onClick={() => {
                            removeInsightFromDashboard(insight, dashboard?.id || 0)
                        }}
                        data-attr="remove-insight-from-dashboard"
                        fullWidth
                        size="small"
                        type="primary"
                        icon={<IconMinusSmall />}
                    />
                ) : (
                    <LemonButton
                        onClick={() => {
                            addInsightToDashboard(insight, dashboard?.id || 0)
                        }}
                        data-attr="add-insight-to-dashboard"
                        fullWidth
                        size="small"
                        type="primary"
                        icon={<IconPlusSmall />}
                    />
                )
            },
        },
    ]

    return (
        <div className="saved-insights">
            {tab === SavedInsightsTabs.History ? (
                <ActivityLog scope={ActivityScope.INSIGHT} />
            ) : tab === SavedInsightsTabs.Alerts ? (
                <Alerts alertId={alertModalId} />
            ) : (
                <>
                    <SavedInsightsFilters />
                    <LemonDivider className="my-4" />
                    <div className="flex justify-between mb-4 gap-2 flex-wrap mt-2 items-center">
                        <span className="text-muted-alt">
                            {count
                                ? `${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${count} insight${
                                      count === 1 ? '' : 's'
                                  }`
                                : null}
                        </span>
                    </div>
                    {!insightsLoading && insights.count < 1 ? (
                        <SavedInsightsEmptyState />
                    ) : (
                        <>
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
                            />
                        </>
                    )}
                </>
            )}
        </div>
    )
}
