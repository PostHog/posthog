import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { INSIGHTS_PER_PAGE, eventInsightsLogic } from 'scenes/data-management/events/eventInsightsLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { InsightIcon } from 'scenes/saved-insights/SavedInsights'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { EventDefinition, QueryBasedInsightModel } from '~/types'

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
                    <>
                        <LemonTableLink
                            to={urls.insightView(insight.short_id)}
                            title={<>{name || <i>{summarizeInsight(insight.query)}</i>}</>}
                            description={insight.description}
                        />
                    </>
                )
            },
            sorter: (a, b) => (a.name || summarizeInsight(a.query)).localeCompare(b.name || summarizeInsight(b.query)),
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
    ]

    return (
        <SceneSection title="Insights using event" className="saved-insights">
            <LemonInput
                type="search"
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
        </SceneSection>
    )
}
