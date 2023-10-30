import { useActions, useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { deleteWithUndo } from 'lib/utils'
import { InsightModel, InsightType, LayoutView, SavedInsightsTabs } from '~/types'
import { INSIGHTS_PER_PAGE, savedInsightsLogic } from './savedInsightsLogic'
import './SavedInsights.scss'
import { organizationLogic } from 'scenes/organizationLogic'
import { PageHeader } from 'lib/components/PageHeader'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { teamLogic } from '../teamLogic'
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
    IconStarFilled,
    IconStarOutline,
    IconTableChart,
    InsightsFunnelsIcon,
    InsightsLifecycleIcon,
    InsightsPathsIcon,
    InsightSQLIcon,
    InsightsRetentionIcon,
    InsightsStickinessIcon,
    InsightsTrendsIcon,
} from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonButton, LemonButtonWithSideAction, LemonButtonWithSideActionProps } from 'lib/lemon-ui/LemonButton'
import { InsightCard } from 'lib/components/Cards/InsightCard'

import { groupsModel } from '~/models/groupsModel'
import { cohortsModel } from '~/models/cohortsModel'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { LemonSelectOptions } from '@posthog/lemon-ui'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { NodeKind } from '~/queries/schema'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { isInsightVizNode } from '~/queries/utils'
import { overlayForNewInsightMenu } from 'scenes/saved-insights/newInsightsMenu'
import { summarizeInsight } from 'scenes/insights/summarizeInsight'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

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
        icon: InsightsTrendsIcon,
        inMenu: true,
    },
    [InsightType.FUNNELS]: {
        name: 'Funnel',
        description: 'Discover how many users complete or drop out of a sequence of actions.',
        icon: InsightsFunnelsIcon,
        inMenu: true,
    },
    [InsightType.RETENTION]: {
        name: 'Retention',
        description: 'See how many users return on subsequent days after an intial action.',
        icon: InsightsRetentionIcon,
        inMenu: true,
    },
    [InsightType.PATHS]: {
        name: 'Paths',
        description: 'Trace the journeys users take within your product and where they drop off.',
        icon: InsightsPathsIcon,
        inMenu: true,
    },
    [InsightType.STICKINESS]: {
        name: 'Stickiness',
        description: 'See what keeps users coming back by viewing the interval between repeated actions.',
        icon: InsightsStickinessIcon,
        inMenu: true,
    },
    [InsightType.LIFECYCLE]: {
        name: 'Lifecycle',
        description: 'Understand growth by breaking down new, resurrected, returning and dormant users.',
        icon: InsightsLifecycleIcon,
        inMenu: true,
    },
    [InsightType.SQL]: {
        name: 'SQL',
        description: 'Use HogQL to query your data.',
        icon: InsightSQLIcon,
        inMenu: true,
    },
    [InsightType.JSON]: {
        name: 'Custom',
        description: 'Save components powered by our JSON query language.',
        icon: InsightSQLIcon,
        inMenu: true,
    },
}

export const QUERY_TYPES_METADATA: Record<NodeKind, InsightTypeMetadata> = {
    [NodeKind.TrendsQuery]: {
        name: 'Trends',
        description: 'Visualize and break down how actions or events vary over time',
        icon: InsightsTrendsIcon,
        inMenu: true,
    },
    [NodeKind.FunnelsQuery]: {
        name: 'Funnel',
        description: 'Discover how many users complete or drop out of a sequence of actions',
        icon: InsightsFunnelsIcon,
        inMenu: true,
    },
    [NodeKind.RetentionQuery]: {
        name: 'Retention',
        description: 'See how many users return on subsequent days after an intial action',
        icon: InsightsRetentionIcon,
        inMenu: true,
    },
    [NodeKind.PathsQuery]: {
        name: 'Paths',
        description: 'Trace the journeys users take within your product and where they drop off',
        icon: InsightsPathsIcon,
        inMenu: true,
    },
    [NodeKind.StickinessQuery]: {
        name: 'Stickiness',
        description: 'See what keeps users coming back by viewing the interval between repeated actions',
        icon: InsightsStickinessIcon,
        inMenu: true,
    },
    [NodeKind.LifecycleQuery]: {
        name: 'Lifecycle',
        description: 'Understand growth by breaking down new, resurrected, returning and dormant users',
        icon: InsightsLifecycleIcon,
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
    [NodeKind.PersonsQuery]: {
        name: 'Persons',
        description: 'List of persons matching specified conditions',
        icon: IconPerson,
        inMenu: false,
    },
    [NodeKind.InsightPersonsQuery]: {
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
        icon: InsightsTrendsIcon,
        inMenu: true,
    },
    [NodeKind.HogQLQuery]: {
        name: 'HogQL',
        description: 'Direct HogQL query',
        icon: InsightSQLIcon,
        inMenu: true,
    },
    [NodeKind.HogQLMetadata]: {
        name: 'HogQL Metadata',
        description: 'Metadata for a HogQL query',
        icon: InsightSQLIcon,
        inMenu: true,
    },
    [NodeKind.DatabaseSchemaQuery]: {
        name: 'Database Schema',
        description: 'Introspect the PostHog database schema',
        icon: InsightSQLIcon,
        inMenu: true,
    },
    [NodeKind.WebOverviewQuery]: {
        name: 'Overview Stats',
        description: 'View overview stats for a website',
        icon: InsightsTrendsIcon,
        inMenu: true,
    },
    [NodeKind.WebStatsTableQuery]: {
        name: 'Web Table',
        description: 'A table of results from web analytics, with a breakdown',
        icon: InsightsTrendsIcon,
        inMenu: true,
    },
    [NodeKind.WebTopClicksQuery]: {
        name: 'Top Clicks',
        description: 'View top clicks for a website',
        icon: InsightsTrendsIcon,
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
        return <insightMetadata.icon style={{ display: 'block', fontSize: '2rem' }} />
    }
    return null
}

export function NewInsightButton({ dataAttr }: NewInsightButtonProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const overrides3000: Partial<LemonButtonWithSideActionProps> = featureFlags[FEATURE_FLAGS.POSTHOG_3000]
        ? {
              size: 'small',
              icon: <IconPlusMini />,
          }
        : {}

    return (
        <LemonButtonWithSideAction
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
            {...overrides3000}
        >
            New insight
        </LemonButtonWithSideAction>
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
                        deleteWithUndo={() =>
                            deleteWithUndo({
                                object: insight,
                                endpoint: `projects/${currentTeamId}/insights`,
                                callback: loadInsights,
                            })
                        }
                        placement={'SavedInsightGrid'}
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
                                        <IconStarOutline className="text-muted" />
                                    )
                                }
                                tooltip={`${insight.favorited ? 'Add to' : 'Remove from'} favorite insights`}
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
                    <div className={'whitespace-nowrap'}>{last_modified_at && <TZLabel time={last_modified_at} />}</div>
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
                                <LemonButton status="stealth" to={urls.insightView(insight.short_id)} fullWidth>
                                    View
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton status="stealth" to={urls.insightEdit(insight.short_id)} fullWidth>
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    status="stealth"
                                    onClick={() => renameInsight(insight)}
                                    data-attr={`insight-item-${insight.short_id}-dropdown-rename`}
                                    fullWidth
                                >
                                    Rename
                                </LemonButton>
                                <LemonButton
                                    status="stealth"
                                    onClick={() => duplicateInsight(insight)}
                                    data-attr={`duplicate-insight-from-list-view`}
                                    fullWidth
                                >
                                    Duplicate
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    status="danger"
                                    onClick={() =>
                                        deleteWithUndo({
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
            <PageHeader title="Insights" buttons={<NewInsightButton dataAttr="saved-insights-create-new-insight" />} />
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
                    <div className="flex justify-between mb-4 mt-2 items-center">
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
