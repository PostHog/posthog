import './SavedInsights.scss'

import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheck } from '@posthog/icons'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { urls } from 'scenes/urls'

import { QueryBasedInsightModel } from '~/types'

import { InsightIcon } from './SavedInsights'
import { INSIGHTS_PER_PAGE, addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'
import { insightDashboardModalLogic } from './insightDashboardModalLogic'

interface SavedInsightsTableProps {
    dashboardId?: number
    renderActionColumn?: (insight: QueryBasedInsightModel) => JSX.Element
    title?: string
}

export function SavedInsightsTable({ dashboardId, renderActionColumn, title }: SavedInsightsTableProps): JSX.Element {
    const isExperimentEnabled = useFeatureFlag('ADD_INSIGHT_TO_DASHBOARD_MODAL_EXPERIMENT')
    const { modalPage, insights, count, insightsLoading, filters, sorting } = useValues(addSavedInsightsModalLogic)
    const { setModalPage, setModalFilters } = useActions(addSavedInsightsModalLogic)
    const { dashboardUpdatesInProgress, isInsightInDashboard } = useValues(insightDashboardModalLogic)
    const { toggleInsightOnDashboard, syncOptimisticStateWithDashboard } = useActions(insightDashboardModalLogic)
    const { dashboard } = useValues(dashboardLogic)
    const summarizeInsight = useSummarizeInsight()

    const startCount = (modalPage - 1) * INSIGHTS_PER_PAGE + 1
    const endCount = Math.min(modalPage * INSIGHTS_PER_PAGE, count)

    const useDashboardMode = isExperimentEnabled && dashboardId !== undefined

    useEffect(() => {
        if (useDashboardMode && dashboard?.tiles) {
            syncOptimisticStateWithDashboard(dashboard.tiles)
        }
    }, [dashboard?.tiles, useDashboardMode, syncOptimisticStateWithDashboard])

    const handleRowClick = (insight: QueryBasedInsightModel): void => {
        if (!useDashboardMode || !dashboardId) {
            return
        }
        if (dashboardUpdatesInProgress[insight.id]) {
            return
        }
        toggleInsightOnDashboard(insight, dashboardId, isInsightInDashboard(insight, dashboard?.tiles))
    }

    const columns: LemonTableColumns<QueryBasedInsightModel> = [
        ...(renderActionColumn
            ? [
                  {
                      width: 0,
                      render: (_: unknown, insight: QueryBasedInsightModel) => renderActionColumn(insight),
                  },
              ]
            : []),
        {
            key: 'id',
            width: 32,
            render: function renderType(_, insight) {
                return <InsightIcon insight={insight} className="text-secondary text-2xl" />
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: 300,
            render: function renderName(name: string, insight) {
                const displayName = name || summarizeInsight(insight.query)
                return (
                    <div className="flex flex-col gap-1 min-w-0">
                        <div className="flex min-w-0">
                            {useDashboardMode ? (
                                <Tooltip title={displayName}>
                                    <span className="block truncate">{name || <i>{displayName}</i>}</span>
                                </Tooltip>
                            ) : (
                                <Tooltip title={displayName}>
                                    <Link
                                        to={urls.insightView(insight.short_id)}
                                        target="_blank"
                                        className="w-0 flex-1 min-w-0"
                                        onClick={(e) => e.stopPropagation()}
                                    >
                                        <span className="block truncate">{name || <i>{displayName}</i>}</span>
                                    </Link>
                                </Tooltip>
                            )}
                        </div>
                        {insight.description && (
                            <div className="text-xs text-tertiary truncate">{insight.description}</div>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Tags',
            dataIndex: 'tags' as keyof QueryBasedInsightModel,
            key: 'tags',
            render: function renderTags(tags: string[]) {
                return <ObjectTags tags={tags} staticOnly />
            },
        },
        createdByColumn() as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>,
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
        ...(useDashboardMode
            ? [
                  {
                      key: 'status',
                      width: 32,
                      render: function renderStatus(_: unknown, insight: QueryBasedInsightModel) {
                          return isInsightInDashboard(insight, dashboard?.tiles) ? (
                              <IconCheck className="text-success text-xl" />
                          ) : null
                      },
                  },
              ]
            : []),
    ]

    return (
        <div className="saved-insights">
            {title ? (
                <div className="flex items-center gap-4 mb-2">
                    <h4 className="font-semibold m-0 shrink-0">{title}</h4>
                    <div className="flex-1">
                        <SavedInsightsFilters filters={filters} setFilters={setModalFilters} showQuickFilters={false} />
                    </div>
                </div>
            ) : (
                <SavedInsightsFilters filters={filters} setFilters={setModalFilters} showQuickFilters={false} />
            )}
            <LemonDivider className="my-4" />
            <div className="flex justify-between mb-4 gap-2 flex-wrap mt-2 items-center">
                <span className="text-secondary">
                    {count
                        ? `${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${pluralize(count, 'insight')}`
                        : null}
                </span>
            </div>
            {!insightsLoading && insights.count < 1 ? (
                <SavedInsightsEmptyState filters={filters} usingFilters />
            ) : (
                <LemonTable
                    dataSource={insights.results}
                    columns={columns}
                    loading={insightsLoading}
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
                        setModalFilters({
                            order: newSorting
                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                : undefined,
                        })
                    }
                    rowKey="id"
                    loadingSkeletonRows={INSIGHTS_PER_PAGE}
                    nouns={['insight', 'insights']}
                    rowClassName={
                        useDashboardMode
                            ? (insight) =>
                                  isInsightInDashboard(insight, dashboard?.tiles)
                                      ? 'bg-success-highlight border-l-2 border-l-success cursor-pointer hover:bg-success-highlight/70'
                                      : 'cursor-pointer hover:bg-primary-highlight border-l-2 border-l-transparent hover:border-l-primary'
                            : undefined
                    }
                    onRow={
                        useDashboardMode
                            ? (insight) => ({
                                  onClick: () => handleRowClick(insight),
                                  title: isInsightInDashboard(insight, dashboard?.tiles)
                                      ? 'Click to remove from dashboard'
                                      : 'Click to add to dashboard',
                              })
                            : undefined
                    }
                />
            )}
        </div>
    )
}
