import './SavedInsights.scss'

import {
    IconBrackets,
    IconFunnels,
    IconHogQL,
    IconLifecycle,
    IconRetention,
    IconStar,
    IconStarFilled,
    IconStickiness,
    IconTrends,
    IconUserPaths,
} from '@posthog/icons'
import { LemonSelectOptions } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { InsightCard } from 'lib/components/Cards/InsightCard'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { TZLabel } from 'lib/components/TZLabel'
import {
    IconAction,
    IconBarChart,
    IconCoffee,
    IconEvent,
    IconGridView,
    IconListView,
    IconPerson,
    IconPlusMini,
    IconSelectEvents,
    IconTableChart,
} from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { Link } from 'lib/lemon-ui/Link'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { summarizeInsight } from 'scenes/insights/summarizeInsight'
import { organizationLogic } from 'scenes/organizationLogic'
import { overlayForNewInsightMenu } from 'scenes/saved-insights/newInsightsMenu'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { SceneExport } from 'scenes/sceneTypes'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { urls } from 'scenes/urls'

import { cohortsModel } from '~/models/cohortsModel'
import { groupsModel } from '~/models/groupsModel'
import { NodeKind } from '~/queries/schema'
import { isInsightVizNode } from '~/queries/utils'
import { ActivityScope, InsightModel, InsightType, LayoutView, SavedInsightsTabs } from '~/types'

import { teamLogic } from '../teamLogic'
import { INSIGHTS_PER_PAGE, savedInsightsLogic } from './savedInsightsLogic'

interface NewInsightButtonProps {
    dataAttr: string
}

export interface InsightTypeMetadata {
    name: string
    description?: string
    icon: (props?: any) => JSX.Element
    inMenu: boolean
}

export const INSIGHT_TYPES_METADATA: Record<InsightType, InsightTypeMetadata> = {
    [InsightType.TRENDS]: {
        name: 'Trends',
        description: 'Visualize and break down how actions or events vary over time.',
        icon: IconTrends,
        inMenu: true,
    },
    [InsightType.FUNNELS]: {
        name: 'Funnel',
        description: 'Discover how many users complete or drop out of a sequence of actions.',
        icon: IconFunnels,
        inMenu: true,
    },
    [InsightType.RETENTION]: {
        name: 'Retention',
        description: 'See how many users return on subsequent days after an intial action.',
        icon: IconRetention,
        inMenu: true,
    },
    [InsightType.PATHS]: {
        name: 'Paths',
        description: 'Trace the journeys users take within your product and where they drop off.',
        icon: IconUserPaths,
        inMenu: true,
    },
    [InsightType.STICKINESS]: {
        name: 'Stickiness',
        description: 'See what keeps users coming back by viewing the interval between repeated actions.',
        icon: IconStickiness,
        inMenu: true,
    },
    [InsightType.LIFECYCLE]: {
        name: 'Lifecycle',
        description: 'Understand growth by breaking down new, resurrected, returning and dormant users.',
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
}

export const QUERY_TYPES_METADATA: Record<NodeKind, InsightTypeMetadata> = {
    [NodeKind.TrendsQuery]: {
        name: 'Trends',
        description: 'Visualize and break down how actions or events vary over time',
        icon: IconTrends,
        inMenu: true,
    },
    [NodeKind.FunnelsQuery]: {
        name: 'Funnel',
        description: 'Discover how many users complete or drop out of a sequence of actions',
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
        description: 'Trace the journeys users take within your product and where they drop off',
        icon: IconUserPaths,
        inMenu: true,
    },
    [NodeKind.StickinessQuery]: {
        name: 'Stickiness',
        description: 'See what keeps users coming back by viewing the interval between repeated actions',
        icon: IconStickiness,
        inMenu: true,
    },
    [NodeKind.LifecycleQuery]: {
        name: 'Lifecycle',
        description: 'Understand growth by breaking down new, resurrected, returning and dormant users',
        icon: IconLifecycle,
        inMenu: true,
    },
    [NodeKind.EventsNode]: {
        name: 'Events',
        description: 'List and explore events',
        icon: IconSelectEvents,
        inMenu: true,
    },
    [NodeKind.ActionsNode]: {
        name: 'Actions',
        description: 'List and explore actions',
        icon: IconAction,
        inMenu: true,
    },
    [NodeKind.EventsQuery]: {
        name: 'Events Query',
        description: 'Hmmm, not every kind should be displayable I guess',
        icon: IconEvent,
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
        icon: IconBarChart,
        inMenu: true,
    },
    [NodeKind.InsightVizNode]: {
        name: 'Insight visualization',
        description: 'View your insights',
        icon: IconBarChart,
        inMenu: true,
    },
    [NodeKind.TimeToSeeDataSessionsQuery]: {
        name: 'Internal PostHog performance data',
        description: 'View performance data about a session in PostHog itself',
        icon: IconCoffee,
        inMenu: true,
    },
    [NodeKind.TimeToSeeDataQuery]: {
        name: 'Internal PostHog performance data',
        description: 'View listings of sessions holding performance data in PostHog itself',
        icon: IconCoffee,
        inMenu: true,
    },
    [NodeKind.TimeToSeeDataSessionsJSONNode]: {
        name: 'Internal PostHog performance data',
        description: 'View performance data about a session in PostHog itself as JSON',
        icon: IconCoffee,
        inMenu: true,
    },
    [NodeKind.TimeToSeeDataSessionsWaterfallNode]: {
        name: 'Internal PostHog performance data',
        description: 'View performance data about a session in PostHog itself in a trace/waterfall view',
        icon: IconCoffee,
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
        icon: IconHogQL,
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
        icon: IconTrends,
        inMenu: true,
    },
    [NodeKind.WebStatsTableQuery]: {
        name: 'Web Table',
        description: 'A table of results from web analytics, with a breakdown',
        icon: IconTrends,
        inMenu: true,
    },
    [NodeKind.WebTopClicksQuery]: {
        name: 'Top Clicks',
        description: 'View top clicks for a website',
        icon: IconTrends,
        inMenu: true,
    },
}

export const INSIGHT_TYPE_OPTIONS: LemonSelectOptions<string> = [
    { value: 'All types', label: 'All types' },
    ...Object.entries(INSIGHT_TYPES_METADATA).map(([value, meta]) => ({
        value,
        label: meta.name,
        icon: meta.icon ? <meta.icon color="#747EA2" noBackground /> : undefined,
    })),
]

export const scene: SceneExport = {
    component: SavedInsights,
    logic: savedInsightsLogic,
}

export function InsightIcon({ insight }: { insight: InsightModel }): JSX.Element | null {
    let insightType = insight?.filters?.insight || InsightType.TRENDS
    if (!!insight.query && !isInsightVizNode(insight.query)) {
        insightType = InsightType.JSON
    }
    const insightMetadata = INSIGHT_TYPES_METADATA[insightType]
    if (insightMetadata && insightMetadata.icon) {
        return <insightMetadata.icon />
    }
    return null
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
            icon={<IconPlusMini />}
        >
            New insight
        </LemonButton>
    )
}

function SavedInsightsGrid(): JSX.Element {
    const { loadInsights, renameInsight, duplicateInsight } = useActions(savedInsightsLogic)
    const { insights, insightsLoading, pagination } = useValues(savedInsightsLogic)
    const { currentTeamId } = useValues(teamLogic)

    const paginationState = usePagination(insights?.results || [], pagination)

    return (
        <>
            <div className="saved-insights-grid mb-2">
                {paginationState.dataSourcePage.map((insight: InsightModel) => (
                    <InsightCard
                        key={insight.short_id}
                        insight={{ ...insight }}
                        rename={() => renameInsight(insight)}
                        duplicate={() => duplicateInsight(insight)}
                        deleteWithUndo={async () =>
                            await deleteWithUndo({
                                object: insight,
                                endpoint: `projects/${currentTeamId}/insights`,
                                callback: loadInsights,
                            })
                        }
                        placement="SavedInsightGrid"
                    />
                ))}
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
    const { insights, count, insightsLoading, filters, sorting, pagination } = useValues(savedInsightsLogic)
    const { hasDashboardCollaboration } = useValues(organizationLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { mathDefinitions } = useValues(mathsLogic)

    const { tab, layoutView, page } = filters

    const startCount = (page - 1) * INSIGHTS_PER_PAGE + 1
    const endCount = page * INSIGHTS_PER_PAGE < count ? page * INSIGHTS_PER_PAGE : count

    const columns: LemonTableColumns<InsightModel> = [
        {
            key: 'id',
            className: 'icon-column',
            width: 32,
            render: function renderType(_, insight) {
                return <InsightIcon insight={insight} />
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function renderName(name: string, insight) {
                return (
                    <>
                        <span className="row-name">
                            <Link to={urls.insightView(insight.short_id)}>
                                {name || (
                                    <i>
                                        {summarizeInsight(insight.query, insight.filters, {
                                            aggregationLabel,
                                            cohortsById,
                                            mathDefinitions,
                                        })}
                                    </i>
                                )}
                            </Link>
                            <LemonButton
                                className="ml-1"
                                size="small"
                                onClick={() => updateFavoritedInsight(insight, !insight.favorited)}
                                icon={
                                    insight.favorited ? (
                                        <IconStarFilled className="text-warning" />
                                    ) : (
                                        <IconStar className="text-muted" />
                                    )
                                }
                                tooltip={`${insight.favorited ? 'Remove from' : 'Add to'} favorite insights`}
                            />
                        </span>
                        {hasDashboardCollaboration && insight.description && (
                            <LemonMarkdown className="row-description" lowKeyHeadings>
                                {insight.description}
                            </LemonMarkdown>
                        )}
                    </>
                )
            },
        },
        ...(hasDashboardCollaboration
            ? [
                  {
                      title: 'Tags',
                      dataIndex: 'tags' as keyof InsightModel,
                      key: 'tags',
                      render: function renderTags(tags: string[]) {
                          return <ObjectTags tags={tags} staticOnly />
                      },
                  },
              ]
            : []),
        ...(tab === SavedInsightsTabs.Yours
            ? []
            : [createdByColumn() as LemonTableColumn<InsightModel, keyof InsightModel | undefined>]),
        createdAtColumn() as LemonTableColumn<InsightModel, keyof InsightModel | undefined>,
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
                                        void deleteWithUndo({
                                            object: insight,
                                            endpoint: `projects/${currentTeamId}/insights`,
                                            callback: loadInsights,
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
