import { LemonInput, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { urls } from 'scenes/urls'

import { EventDefinition, QueryBasedInsightModel } from '~/types'

import { eventInsightsLogic, INSIGHTS_PER_PAGE } from 'scenes/data-management/events/eventInsightsLogic'
import { InsightIcon } from 'scenes/saved-insights/SavedInsights'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'

export function EventDefinitionInsights({ definition }: { definition: EventDefinition }): JSX.Element {
    const event = definition.name
    const { page, insights, filters, insightsLoading, sorting } = useValues(eventInsightsLogic({ event }))
    const { setPage, setFilters } = useActions(eventInsightsLogic({ event }))
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
            render: function renderName(name: string, insight) {
                return (
                    <div className="flex flex-col gap-1">
                        <div className="inline-flex">
                            <Link to={urls.insightView(insight.short_id)} target="_blank">
                                {name || <i>{summarizeInsight(insight.query)}</i>}
                            </Link>
                        </div>
                        <div className="text-xs text-tertiary">{insight.description}</div>
                    </div>
                )
            },
        },
        createdByColumn() as LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>,
    ]

    return (
        <div className="saved-insights">
            <h3>Insights using event</h3>
            <LemonInput
                type="search"
                className="mb-2"
                placeholder="Search..."
                onChange={(value) => setFilters({ search: value })}
                value={filters.search || ''}
            />
            <LemonTable
                id={`event-definition-insights-table-${definition.id}`}
                loading={insightsLoading}
                columns={columns}
                data-attr="event-definition-insights-table"
                dataSource={insights.results}
                pagination={{
                    controlled: true,
                    currentPage: page ?? 1,
                    entryCount: insights.count,
                    pageSize: INSIGHTS_PER_PAGE,
                    onForward: insights.next
                        ? () => {
                              setPage(page + 1)
                          }
                        : undefined,
                    onBackward: insights.previous
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
