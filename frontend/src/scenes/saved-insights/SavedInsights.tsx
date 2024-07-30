import './SavedInsights.scss'

import {
    IconBrackets,
    IconCorrelationAnalysis,
    IconCursor,
    IconFunnels,
    IconGraph,
    IconHogQL,
    IconLifecycle,
    IconPerson,
    IconPieChart,
    IconPlusSmall,
    IconRetention,
    IconStar,
    IconStarFilled,
    IconStickiness,
    IconTrends,
    IconUserPaths,
    IconWarning,
} from '@posthog/icons'
import { LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { InsightCard } from 'lib/components/Cards/InsightCard'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { IconAction, IconGridView, IconListView, IconTableChart } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { isNonEmptyObject } from 'lib/utils'
import { deleteInsightWithUndo } from 'lib/utils/deleteWithUndo'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { organizationLogic } from 'scenes/organizationLogic'
import { overlayForNewInsightMenu } from 'scenes/saved-insights/newInsightsMenu'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema'
import { isNodeWithSource } from '~/queries/utils'
import { ActivityScope, InsightType, LayoutView, QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { teamLogic } from '../teamLogic'
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
    [NodeKind.WebTopClicksQuery]: {
        name: 'Top Clicks',
        description: 'View top clicks for a website',
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
}

export function InsightIcon({
    insight,
    className,
}: {
    insight: QueryBasedInsightModel
    className?: string
}): JSX.Element | null {
    let Icon: (props?: any) => JSX.Element | null = () => null

    if ('filters' in insight && isNonEmptyObject(insight.filters)) {
        const insightType = insight.filters.insight || InsightType.TRENDS
        const insightMetadata = INSIGHT_TYPES_METADATA[insightType]
        Icon = insightMetadata && insightMetadata.icon
    } else if ('query' in insight && isNonEmptyObject(insight.query)) {
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

function SavedInsightsGrid(): JSX.Element {
    const { loadInsights, renameInsight, duplicateInsight } = useActions(savedInsightsLogic)
    const { insights, insightsLoading, pagination, queryBasedInsightSaving } = useValues(savedInsightsLogic)
    const { currentTeamId } = useValues(teamLogic)

    const paginationState = usePagination(insights?.results || [], pagination)

    return (
        <>
            <div className="saved-insights-grid mb-2">
                {paginationState.dataSourcePage.map((insight) => {
                    return (
                        <InsightCard
                            key={insight.short_id}
                            insight={insight}
                            rename={() => renameInsight(insight)}
                            duplicate={() => duplicateInsight(insight)}
                            deleteWithUndo={async () =>
                                await deleteInsightWithUndo({
                                    object: insight,
                                    endpoint: `projects/${currentTeamId}/insights`,
                                    callback: loadInsights,
                                    options: {
                                        writeAsQuery: queryBasedInsightSaving,
                                        readAsQuery: true,
                                    },
                                })
                            }
                            placement="SavedInsightGrid"
                        />
                    )
                })}
                {insightsLoading && (
                    // eslint-disable-next-line react/forbid-dom-props
                    <div style={{ minHeight: '30rem' }}>
                        <SpinnerOverlay sceneLevel />
                    </div>
                )}
            </div>
            <PaginationControl {...paginationState} nouns={['insight', 'insights']} bordered />
        </>
    )
}

export function SavedInsights(): JSX.Element {
    const { loadInsights, updateFavoritedInsight, renameInsight, duplicateInsight, setSavedInsightsFilters } =
        useActions(savedInsightsLogic)
    const { insights, count, insightsLoading, filters, sorting, pagination, queryBasedInsightSaving } =
        useValues(savedInsightsLogic)
    const { hasTagging } = useValues(organizationLogic)
    const { currentTeamId } = useValues(teamLogic)
    const summarizeInsight = useSummarizeInsight()

    const { tab, layoutView, page } = filters

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
                            title={
                                <>
                                    {name || <i>{summarizeInsight(insight.query)}</i>}

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
                                                <IconStar className="text-muted" />
                                            )
                                        }
                                        tooltip={`${insight.favorited ? 'Remove from' : 'Add to'} favorite insights`}
                                    />
                                </>
                            }
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
                return (
                    <More
                        overlay={
                            <>
                                <LemonButton to={urls.insightView(insight.short_id)} fullWidth>
                                    View
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton to={urls.insightEdit(insight.short_id)} fullWidth>
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    onClick={() => renameInsight(insight)}
                                    data-attr={`insight-item-${insight.short_id}-dropdown-rename`}
                                    fullWidth
                                >
                                    Rename
                                </LemonButton>
                                <LemonButton
                                    onClick={() => duplicateInsight(insight)}
                                    data-attr="duplicate-insight-from-list-view"
                                    fullWidth
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    status="danger"
                                    onClick={() =>
                                        void deleteInsightWithUndo({
                                            object: insight,
                                            endpoint: `projects/${currentTeamId}/insights`,
                                            callback: loadInsights,
                                            options: {
                                                writeAsQuery: queryBasedInsightSaving,
                                                readAsQuery: true,
                                            },
                                        })
                                    }
                                    data-attr={`insight-item-${insight.short_id}-dropdown-remove`}
                                    fullWidth
                                >
                                    Delete insight
                                </LemonButton>
                            </>
                        }
                    />
                )
            },
        },
    ]

    return (
        <div className="saved-insights">
            <PageHeader buttons={<NewInsightButton dataAttr="saved-insights-create-new-insight" />} />
            <LemonTabs
                activeKey={tab}
                onChange={(tab) => setSavedInsightsFilters({ tab })}
                tabs={[
                    { key: SavedInsightsTabs.All, label: 'All insights' },
                    { key: SavedInsightsTabs.Yours, label: 'Your insights' },
                    { key: SavedInsightsTabs.Favorites, label: 'Favorites' },
                    { key: SavedInsightsTabs.History, label: 'History' },
                ]}
            />

            {tab === SavedInsightsTabs.History ? (
                <ActivityLog scope={ActivityScope.INSIGHT} />
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
                        <div>
                            <LemonSegmentedButton
                                onChange={(newValue) => setSavedInsightsFilters({ layoutView: newValue })}
                                value={layoutView}
                                options={[
                                    {
                                        value: LayoutView.List,
                                        label: 'List',
                                        icon: <IconListView />,
                                    },
                                    {
                                        value: LayoutView.Card,
                                        label: 'Cards',
                                        icon: <IconGridView />,
                                    },
                                ]}
                                size="small"
                            />
                        </div>
                    </div>
                    {!insightsLoading && insights.count < 1 ? (
                        <SavedInsightsEmptyState />
                    ) : (
                        <>
                            {layoutView === LayoutView.List ? (
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
                            ) : (
                                <SavedInsightsGrid />
                            )}
                        </>
                    )}
                </>
            )}
        </div>
    )
}
