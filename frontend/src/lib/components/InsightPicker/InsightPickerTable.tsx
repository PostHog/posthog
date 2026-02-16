import { useActions, useValues } from 'kea'

import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { pluralize } from 'lib/utils'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { INSIGHT_TYPE_OPTIONS, InsightIcon } from 'scenes/saved-insights/SavedInsights'

import { QueryBasedInsightModel } from '~/types'

import { InsightPickerLogicProps, insightPickerLogic } from './insightPickerLogic'

export interface InsightPickerTableProps {
    logicKey: string
    renderActionColumn: (insight: QueryBasedInsightModel) => JSX.Element
    insightsPerPage?: number
    showTagsColumn?: boolean
    extraColumns?: LemonTableColumn<QueryBasedInsightModel, keyof QueryBasedInsightModel | undefined>[]
    rowClassName?: (insight: QueryBasedInsightModel) => string
    onRow?: (insight: QueryBasedInsightModel) => Record<string, any>
    filtersSlot?: React.ReactNode
}

export function InsightPickerTable({
    logicKey,
    renderActionColumn,
    insightsPerPage,
    showTagsColumn,
    extraColumns,
    rowClassName,
    onRow,
    filtersSlot,
}: InsightPickerTableProps): JSX.Element {
    const logicProps: InsightPickerLogicProps = { logicKey, insightsPerPage }
    const {
        insights,
        insightsLoading,
        search,
        page,
        insightType,
        count,
        insightsPerPage: perPage,
        sorting,
    } = useValues(insightPickerLogic(logicProps))
    const { setSearch, setPage, setInsightType, setSorting } = useActions(insightPickerLogic(logicProps))
    const summarizeInsight = useSummarizeInsight()

    const startCount = (page - 1) * perPage + 1
    const endCount = Math.min(page * perPage, count)

    const columns: LemonTableColumns<QueryBasedInsightModel> = [
        {
            key: 'actions',
            width: 0,
            render: function renderActions(_, insight) {
                return renderActionColumn(insight)
            },
        },
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
            width: '25%',
            render: function renderName(name: string, insight) {
                const displayName = name || summarizeInsight(insight.query)
                return (
                    <div className="flex flex-col gap-1">
                        <span className="font-semibold truncate">{name || <i>{displayName}</i>}</span>
                        {insight.description && (
                            <span className="text-xs text-tertiary truncate">{insight.description}</span>
                        )}
                    </div>
                )
            },
        },
        ...(showTagsColumn
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
        createdByColumn() as any,
        createdAtColumn() as any,
        ...(extraColumns || []),
    ]

    return (
        <div className="space-y-4">
            <div className="flex gap-2">
                <LemonInput
                    type="search"
                    placeholder="Search insights..."
                    value={search}
                    onChange={setSearch}
                    className="flex-1"
                />
                {filtersSlot || (
                    <LemonSelect
                        options={INSIGHT_TYPE_OPTIONS}
                        value={insightType}
                        onChange={(value) => setInsightType(value || 'All types')}
                        dropdownMatchSelectWidth={false}
                    />
                )}
            </div>

            {count > 0 && (
                <span className="text-secondary text-sm">
                    {startCount}
                    {endCount - startCount > 0 ? `-${endCount}` : ''} of {pluralize(count, 'insight')}
                </span>
            )}

            <LemonTable
                dataSource={insights.results}
                columns={columns}
                loading={insightsLoading}
                pagination={{
                    controlled: true,
                    currentPage: page,
                    pageSize: perPage,
                    entryCount: count,
                    onForward: () => setPage(page + 1),
                    onBackward: () => setPage(page - 1),
                }}
                sorting={sorting}
                useURLForSorting={false}
                onSort={(newSorting) => setSorting(newSorting)}
                rowKey="id"
                loadingSkeletonRows={perPage}
                nouns={['insight', 'insights']}
                rowClassName={rowClassName}
                onRow={onRow}
            />
        </div>
    )
}
