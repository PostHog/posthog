import './SavedInsights.scss'

import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo } from 'react'

import { IconCheck, IconPlus, IconX } from '@posthog/icons'

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
    const {
        modalPage,
        insights,
        count,
        insightsLoading,
        filters,
        sorting,
        insightsPerPage,
        createdByStrategy,
        userInsights,
    } = useValues(addSavedInsightsModalLogic)
    const { setModalPage, setModalFilters } = useActions(addSavedInsightsModalLogic)
    const { dashboardUpdatesInProgress, isInsightInDashboard } = useValues(insightDashboardModalLogic)
    const { toggleInsightOnDashboard, syncOptimisticStateWithDashboard } = useActions(insightDashboardModalLogic)
    const summarizeInsight = useSummarizeInsight()

    const startCount = (modalPage - 1) * insightsPerPage + 1
    const endCount = Math.min(modalPage * insightsPerPage, count)

    const displayResults = useMemo(() => {
        if (createdByStrategy !== 'highlight' || modalPage !== 1) {
            return insights.results
        }
        const userInsightIds = new Set(userInsights.map((i) => i.id))
        const otherInsights = insights.results.filter((i) => !userInsightIds.has(i.id))
        return [...userInsights, ...otherInsights]
    }, [createdByStrategy, userInsights, insights.results, modalPage])

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
                              <div className="group/status relative flex items-center justify-center">
                                  <IconCheck className="text-success text-xl transition-opacity duration-150 group-hover/status:opacity-0" />
                                  <IconX className="text-danger text-xl absolute inset-0 opacity-0 transition-opacity duration-150 group-hover/status:opacity-100" />
                              </div>
                          ) : (
                              <IconPlus className="text-muted text-xl opacity-40 group-hover:opacity-100 group-hover:text-success transition-all" />
                          )
                      },
                  },
              ]
            : []),
    ]

    return (
        <div className="saved-insights">
            {isExperimentEnabled ? (
                <div className="mb-2">
                    <SavedInsightsFilters
                        filters={filters}
                        setFilters={setModalFilters}
                        showFeatureFlagToggle={false}
                        showFavorites={false}
                    />
                </div>
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
                        dataSource={displayResults}
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
                                          ? 'group bg-white border-l-2 border-l-success cursor-pointer hover:bg-success-highlight'
                                          : 'group cursor-pointer hover:bg-white border-l-2 border-l-transparent hover:border-l-success/50'
                                : undefined
                        }
                        onRow={
                            isExperimentEnabled
                                ? (insight) => ({
                                      onClick: () => handleRowClick(insight),
                                  })
                                : undefined
                        }
                    />
                </div>
            )}
        </div>
    )
}
