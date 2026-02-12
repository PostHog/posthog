import './SavedInsights.scss'

import { useActions, useValues } from 'kea'

import { IconCheck, IconPlus, IconX } from '@posthog/icons'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { SavedInsightsModalEmptyState } from 'scenes/insights/EmptyStates'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { SavedInsightsFilters } from 'scenes/saved-insights/SavedInsightsFilters'

import { QueryBasedInsightModel } from '~/types'

import { InsightIcon } from './SavedInsights'
import { addSavedInsightsModalLogic } from './addSavedInsightsModalLogic'

interface SavedInsightsTableProps {
    isSelected?: (insight: QueryBasedInsightModel) => boolean
    onToggle?: (insight: QueryBasedInsightModel) => void
    isToggling?: (insight: QueryBasedInsightModel) => boolean
}

export function SavedInsightsTable({ isSelected, onToggle, isToggling }: SavedInsightsTableProps): JSX.Element {
    const { modalPage, insights, count, insightsLoading, filters, sorting, insightsPerPage } =
        useValues(addSavedInsightsModalLogic)
    const { setModalPage, setModalFilters } = useActions(addSavedInsightsModalLogic)
    const summarizeInsight = useSummarizeInsight()

    const columns: LemonTableColumns<QueryBasedInsightModel> = [
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
                            <Tooltip title={displayName}>
                                <span className="block truncate max-w-full">{name || <i>{displayName}</i>}</span>
                            </Tooltip>
                        </div>
                        {insight.description && (
                            <Tooltip title={insight.description}>
                                <div className="text-xs text-tertiary line-clamp-3">{insight.description}</div>
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Tags',
            dataIndex: 'tags' as keyof QueryBasedInsightModel,
            key: 'tags',
            width: 0,
            render: function renderTags(tags: string[]) {
                return <ObjectTags tags={tags} staticOnly />
            },
        },
        createdByColumn() as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>,
        {
            title: 'Last modified',
            sorter: true,
            dataIndex: 'last_modified_at',
            width: 0,
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div className="whitespace-nowrap">{last_modified_at && <TZLabel time={last_modified_at} />}</div>
                )
            },
        },
        ...(isSelected
            ? [
                  {
                      key: 'status',
                      width: 32,
                      render: function renderStatus(_: unknown, insight: QueryBasedInsightModel) {
                          return isSelected(insight) ? (
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
            <div className="mb-3">
                <SavedInsightsFilters
                    filters={filters}
                    setFilters={setModalFilters}
                    quickFilters={['insightType', 'tags', 'createdBy']}
                />
            </div>
            {!insightsLoading && insights.count < 1 ? (
                <SavedInsightsModalEmptyState
                    search={filters.search}
                    hasFilters={
                        (filters.insightType !== undefined && filters.insightType !== 'All types') ||
                        (filters.createdBy !== undefined && filters.createdBy !== 'All users') ||
                        (filters.tags !== undefined && filters.tags.length > 0)
                    }
                    onClearFilters={() =>
                        setModalFilters({ insightType: 'All types', createdBy: 'All users', tags: [] })
                    }
                    onClearSearch={() => setModalFilters({ search: '' })}
                />
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
                            isSelected
                                ? (insight) =>
                                      isSelected(insight)
                                          ? 'group bg-success-highlight border-l-2 border-l-success cursor-pointer hover:bg-success-highlight/70'
                                          : 'group cursor-pointer hover:bg-success-highlight/30 border-l-2 border-l-transparent hover:border-l-success/50'
                                : undefined
                        }
                        onRow={
                            onToggle
                                ? (insight) => ({
                                      onClick: () => {
                                          if (!isToggling?.(insight)) {
                                              onToggle(insight)
                                          }
                                      },
                                      title: isSelected?.(insight) ? 'Click to deselect' : 'Click to select',
                                  })
                                : undefined
                        }
                    />
                </div>
            )}
        </div>
    )
}
