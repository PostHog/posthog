import './SavedInsights.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
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
import { SavedInsightsEmptyState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'
import { urls } from 'scenes/urls'

import { DashboardType, QueryBasedInsightModel } from '~/types'

import { InsightIcon } from './SavedInsights'
import { addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'
import { insightDashboardModalLogic } from './insightDashboardModalLogic'

interface SavedInsightsTableProps {
    renderActionColumn?: (insight: QueryBasedInsightModel) => JSX.Element
    dashboard?: DashboardType<QueryBasedInsightModel> | null
}

export function SavedInsightsTable({ renderActionColumn, dashboard }: SavedInsightsTableProps): JSX.Element {
    const isExperimentEnabled = useFeatureFlag('PRODUCT_ANALYTICS_ADD_INSIGHT_TO_DASHBOARD_MODAL', 'test')
    const { modalPage, insights, count, insightsLoading, filters, sorting, insightsPerPage } =
        useValues(addSavedInsightsModalLogic)
    const { setModalPage, setModalFilters } = useActions(addSavedInsightsModalLogic)
    const { dashboardUpdatesInProgress, isInsightInDashboard } = useValues(insightDashboardModalLogic)
    const { toggleInsightOnDashboard, syncOptimisticStateWithDashboard } = useActions(insightDashboardModalLogic)
    const summarizeInsight = useSummarizeInsight()

    const startCount = (modalPage - 1) * insightsPerPage + 1
    const endCount = Math.min(modalPage * insightsPerPage, count)

    useEffect(() => {
        if (isExperimentEnabled && dashboard?.tiles) {
            syncOptimisticStateWithDashboard(dashboard.tiles)
        }
    }, [dashboard?.tiles, isExperimentEnabled, syncOptimisticStateWithDashboard])

    const handleRowClick = (insight: QueryBasedInsightModel): void => {
        if (dashboardUpdatesInProgress[insight.id] || !isExperimentEnabled || !dashboard?.id) {
            return
        }

        const currentlyInDashboard = isInsightInDashboard(insight, dashboard.tiles)
        posthog.capture('insight dashboard modal row clicked', {
            action: currentlyInDashboard ? 'remove' : 'add',
            insight_id: insight.id,
            dashboard_id: dashboard.id,
        })
        toggleInsightOnDashboard(insight, dashboard.id, currentlyInDashboard)
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
                    <div className="flex flex-col gap-1 min-w-0 max-w-[300px] overflow-hidden">
                        <div className="flex min-w-0 overflow-hidden">
                            {isExperimentEnabled ? (
                                <Tooltip title={displayName}>
                                    <span className="block truncate max-w-full">{name || <i>{displayName}</i>}</span>
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
                        {insight.description &&
                            (isExperimentEnabled ? (
                                <Tooltip title={insight.description}>
                                    <div className="text-xs text-tertiary line-clamp-3">{insight.description}</div>
                                </Tooltip>
                            ) : (
                                <div className="text-xs text-tertiary truncate">{insight.description}</div>
                            ))}
                    </div>
                )
            },
        },
        {
            title: 'Tags',
            dataIndex: 'tags' as keyof QueryBasedInsightModel,
            key: 'tags',
            ...(isExperimentEnabled ? { width: 0 } : {}),
            render: function renderTags(tags: string[]) {
                return <ObjectTags tags={tags} staticOnly />
            },
        },
        ...(isExperimentEnabled
            ? [createdByColumn() as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>]
            : [
                  createdByColumn() as LemonTableColumn<
                      QueryBasedInsightModel,
                      keyof QueryBasedInsightModel | undefined
                  >,
                  createdAtColumn() as LemonTableColumn<
                      QueryBasedInsightModel,
                      keyof QueryBasedInsightModel | undefined
                  >,
              ]),
        {
            title: 'Last modified',
            sorter: true,
            dataIndex: 'last_modified_at',
            ...(isExperimentEnabled ? { width: 0 } : {}),
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div className="whitespace-nowrap">{last_modified_at && <TZLabel time={last_modified_at} />}</div>
                )
            },
        },
        ...(isExperimentEnabled
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
            {isExperimentEnabled ? (
                <>
                    <SavedInsightsFilters filters={filters} setFilters={setModalFilters} showQuickFilters={false} />
                    <LemonDivider className="my-4" />
                    <div className="flex justify-between mb-4 gap-2 flex-wrap mt-2 items-center">
                        <span className="text-secondary">
                            {count
                                ? `${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${pluralize(count, 'insight')}`
                                : null}
                        </span>
                    </div>
                </>
            ) : (
                <>
                    <SavedInsightsFilters filters={filters} setFilters={setModalFilters} showQuickFilters={false} />
                    <LemonDivider className="my-4" />
                    <div className="flex justify-between mb-4 gap-2 flex-wrap items-center">
                        <span className="text-secondary">
                            {count
                                ? `${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${pluralize(count, 'insight')}`
                                : null}
                        </span>
                    </div>
                </>
            )}
            {!insightsLoading && insights.count < 1 ? (
                <SavedInsightsEmptyState filters={filters} usingFilters />
            ) : (
                <div className="overflow-x-hidden">
                    <LemonTable
                        dataSource={insights.results}
                        columns={columns}
                        loading={insightsLoading}
                        pagination={{
                            controlled: true,
                            currentPage: modalPage,
                            pageSize: insightsPerPage,
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
                        loadingSkeletonRows={insightsPerPage}
                        nouns={['insight', 'insights']}
                        rowClassName={
                            isExperimentEnabled
                                ? (insight) =>
                                      isInsightInDashboard(insight, dashboard?.tiles)
                                          ? 'bg-success-highlight border-l-2 border-l-success cursor-pointer hover:bg-success-highlight/70'
                                          : 'cursor-pointer hover:bg-success-highlight/30 border-l-2 border-l-transparent hover:border-l-success/50'
                                : undefined
                        }
                        onRow={
                            isExperimentEnabled
                                ? (insight) => ({
                                      onClick: () => handleRowClick(insight),
                                      title: isInsightInDashboard(insight, dashboard?.tiles)
                                          ? 'Click to remove from dashboard'
                                          : 'Click to add to dashboard',
                                  })
                                : undefined
                        }
                    />
                </div>
            )}
        </div>
    )
}
