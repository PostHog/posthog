import './SavedInsights.scss'

import { IconMinusSmall, IconPlusSmall } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { Alerts } from 'lib/components/Alerts/views/Alerts'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
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

import { isNodeWithSource } from '~/queries/utils'
import { ActivityScope, QueryBasedInsightModel, SavedInsightsTabs } from '~/types'

import { addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'
import { QUERY_TYPES_METADATA } from './SavedInsights'
import { savedInsightsLogic } from './savedInsightsLogic'

interface NewInsightButtonProps {
    dataAttr: string
}

const INSIGHTS_PER_PAGE = 15

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
    const { modalPage } = useValues(addSavedInsightsModalLogic)
    const { setModalPage } = useActions(addSavedInsightsModalLogic)

    const { insights, count, insightsLoading, filters, sorting, alertModalId, dashboardUpdatesInProgress } =
        useValues(savedInsightsLogic)
    const { setSavedInsightsFilters, addInsightToDashboard, removeInsightFromDashboard } =
        useActions(savedInsightsLogic)

    const { hasTagging } = useValues(organizationLogic)
    const { dashboard } = useValues(dashboardLogic)

    const summarizeInsight = useSummarizeInsight()

    const { tab } = filters

    const startCount = (modalPage - 1) * INSIGHTS_PER_PAGE + 1
    const endCount = Math.min(modalPage * INSIGHTS_PER_PAGE, count)

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
                return (
                    <LemonButton
                        type="secondary"
                        status={isInDashboard ? 'danger' : 'default'}
                        loading={dashboardUpdatesInProgress[insight.id]}
                        size="small"
                        fullWidth
                        onClick={(e) => {
                            e.preventDefault()
                            if (dashboardUpdatesInProgress[insight.id]) {
                                return
                            }
                            isInDashboard
                                ? removeInsightFromDashboard(insight, dashboard?.id || 0)
                                : addInsightToDashboard(insight, dashboard?.id || 0)
                        }}
                    >
                        {isInDashboard ? <IconMinusSmall /> : <IconPlusSmall />}
                    </LemonButton>
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
                                pagination={{
                                    controlled: true,
                                    currentPage: modalPage,
                                    pageSize: INSIGHTS_PER_PAGE,
                                    entryCount: count,
                                    onForward: () => setModalPage(modalPage + 1),
                                    onBackward: () => setModalPage(modalPage - 1),
                                }}
                                sorting={sorting}
                                onSort={(newSorting) =>
                                    setSavedInsightsFilters({
                                        order: newSorting
                                            ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                            : undefined,
                                    })
                                }
                                rowKey="id"
                                loadingSkeletonRows={INSIGHTS_PER_PAGE}
                                nouns={['insight', 'insights']}
                            />
                        </>
                    )}
                </>
            )}
        </div>
    )
}
