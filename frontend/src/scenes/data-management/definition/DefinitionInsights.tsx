import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import {
    DefinitionInsightsLogicProps,
    INSIGHTS_PER_PAGE,
    definitionInsightsLogic,
} from 'scenes/data-management/definition/definitionInsightsLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { InsightIcon } from 'scenes/saved-insights/InsightIcon'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import { Definition, InsightModel } from '~/types'

export interface DefinitionInsightsProps {
    definition: Definition
    filterKey: DefinitionInsightsLogicProps['filterKey']
}

export function DefinitionInsights({ definition, filterKey }: DefinitionInsightsProps): JSX.Element {
    const logic = definitionInsightsLogic({ filterKey, name: definition.name })
    const { page, insights, filters, insightsLoading, sorting } = useValues(logic)
    const { setPage, setFilters } = useActions(logic)
    const isEvent = filterKey === 'events'
    const summarizeInsight = useSummarizeInsight()

    const columns: LemonTableColumns<InsightModel> = [
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
        createdByColumn() as LemonTableColumn<InsightModel, keyof InsightModel | undefined>,
        createdAtColumn() as LemonTableColumn<InsightModel, keyof InsightModel | undefined>,
        {
            title: 'Last modified',
            sorter: true,
            defaultSortOrder: -1,
            dataIndex: 'last_modified_at',
            render: function renderLastModified(last_modified_at: string) {
                return (
                    <div className="whitespace-nowrap">{last_modified_at && <TZLabel time={last_modified_at} />}</div>
                )
            },
        },
    ]

    return (
        <SceneSection
            title={isEvent ? 'Insights using event' : 'Insights using property'}
            description={
                isEvent ? undefined : 'Saved insights that use a property with this name, of any property type.'
            }
            className="saved-insights"
        >
            <LemonInput
                type="search"
                placeholder="Search..."
                onChange={(value) => setFilters({ search: value })}
                value={filters.search || ''}
            />
            <LemonTable
                id={`${isEvent ? 'event' : 'property'}-definition-insights-table-${definition.id}`}
                loading={insightsLoading}
                columns={columns}
                // pinned: data-attr values are used by autocapture dashboards
                data-attr={isEvent ? 'event-definition-insights-table' : 'property-definition-insights-table'}
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
