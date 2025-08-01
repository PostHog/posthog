import { LemonInput, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { useEffect } from 'react'
import { urls } from 'scenes/urls'

import { EventDefinition, QueryBasedInsightModel } from '~/types'

import { eventInsightsLogic, INSIGHTS_PER_PAGE } from 'scenes/data-management/events/eventInsightsLogic'
import { InsightIcon } from 'scenes/saved-insights/SavedInsights'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'

export function EventDefinitionInsights({ definition }: { definition: EventDefinition }): JSX.Element {
    const { page, insights, count, filters, insightsLoading, sorting } = useValues(eventInsightsLogic)
    const { setPage, setFilters } = useActions(eventInsightsLogic)
    const summarizeInsight = useSummarizeInsight()

    const startCount = (page - 1) * INSIGHTS_PER_PAGE + 1
    const endCount = Math.min(page * INSIGHTS_PER_PAGE, count)

    useEffect(() => {
        setFilters({ events: [definition.name] })
    }, [definition, setFilters])

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
            render: function renderName(name: string, insight) {
                return (
                    <>
                        <div className="flex flex-col gap-1">
                            <div className="inline-flex">
                                <Link to={urls.insightView(insight.short_id)} target="_blank">
                                    {name || <i>{summarizeInsight(insight.query)}</i>}
                                </Link>
                            </div>
                            <div className="text-xs text-tertiary">{insight.description}</div>
                        </div>
                    </>
                )
            },
        },
        createdByColumn() as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>,
    ]

    return (
        <div className="saved-insights">
            <h3>Insights using event</h3>
            <div className="flex justify-between mb-4 gap-2 flex-wrap mt-2 items-center">
                <span className="text-secondary">
                    {count
                        ? `${startCount}${endCount - startCount > 1 ? '-' + endCount : ''} of ${count} insight${
                              count === 1 ? '' : 's'
                          }`
                        : null}
                </span>
                <LemonInput
                    type="search"
                    placeholder="Search..."
                    onChange={(value) => setFilters({ search: value })}
                    value={filters.search || ''}
                />
            </div>
            <LemonTable
                id={`event-definition-insights-table-${definition.id}`}
                loading={insightsLoading}
                columns={columns}
                data-attr="event-definition-insights-table"
                dataSource={insights.results ? insights.results : []}
                pagination={{
                    controlled: true,
                    currentPage: page ?? 1,
                    entryCount: insights?.count ?? 0,
                    pageSize: INSIGHTS_PER_PAGE,
                    onForward: insights?.next
                        ? () => {
                              setPage(page + 1)
                          }
                        : undefined,
                    onBackward: insights?.previous
                        ? () => {
                              setPage(page - 1)
                          }
                        : undefined,
                }}
                sorting={sorting}
                onSort={(newSorting) =>
                    setFilters({
                        order: newSorting ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}` : undefined,
                    })
                }
                rowKey="id"
                loadingSkeletonRows={INSIGHTS_PER_PAGE}
                nouns={['insight', 'insights']}
                useURLForSorting={false}
                emptyState="No insights found"
            />
        </div>
    )
}
