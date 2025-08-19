import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'

import { isNotNil } from 'lib/utils'

import {
    ConversionGoalFilter,
    DataTableNode,
    DatabaseSchemaDataWarehouseTable,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsHelperForColumnNames,
    MarketingAnalyticsOrderBy,
    MarketingAnalyticsTableQuery,
    SourceMap,
} from '~/queries/schema/schema-general'
import { DataWarehouseSettingsTab, ExternalDataSource } from '~/types'

import { marketingAnalyticsLogic } from './marketingAnalyticsLogic'
import type { marketingAnalyticsTableLogicType } from './marketingAnalyticsTableLogicType'
import { createMarketingAnalyticsOrderBy, isDraftConversionGoalColumn } from './utils'

export type ExternalTable = {
    name: string
    source_type: string
    id: string
    source_map_id: string
    source_prefix: string
    columns: { name: string; type: string }[]
    url_pattern: string
    sourceUrl: string
    external_type: DataWarehouseSettingsTab
    source_map: SourceMap | null
    schema_name: string
    dw_source_type: string
}

export type NativeSource = {
    source: ExternalDataSource
    tables: DatabaseSchemaDataWarehouseTable[]
}

export const marketingAnalyticsTableLogic = kea<marketingAnalyticsTableLogicType>([
    path(['scenes', 'marketingAnalytics', 'marketingAnalyticsTableLogic']),
    connect(() => ({
        values: [marketingAnalyticsLogic, ['conversion_goals', 'draftConversionGoal']],
        actions: [marketingAnalyticsLogic, ['setDraftConversionGoal']],
    })),
    actions({
        setQuery: (query: DataTableNode) => ({ query }),
    }),
    reducers({
        query: [
            null as DataTableNode | null,
            {
                setQuery: (_, { query }) => query,
            },
        ],
    }),
    selectors({
        defaultColumns: [
            (s) => [s.conversion_goals],
            (conversionGoals: ConversionGoalFilter[]) => {
                const selectColumns = [
                    ...Object.values(MarketingAnalyticsBaseColumns).map((column) => column.toString()),
                    ...conversionGoals
                        .map((goal) => [
                            goal.conversion_goal_name,
                            `${MarketingAnalyticsHelperForColumnNames.CostPer} ${goal.conversion_goal_name}`,
                        ])
                        .flat(),
                ].filter(isNotNil)
                return selectColumns
            },
        ],
        sortedColumns: [
            (s) => [s.defaultColumns, s.query],
            (defaultColumns: string[], query: DataTableNode) => {
                // pinned columns are always at the beginning of the table in the same order as they are in the default columns
                const pinnedColumns = query?.pinnedColumns || []
                const sortedColumns = [
                    ...defaultColumns.filter((column) => pinnedColumns.includes(column)),
                    ...defaultColumns.filter((column) => !pinnedColumns.includes(column)),
                ]
                return sortedColumns
            },
        ],
    }),
    /* Both in actionToUrl and urlToAction we need to filter out the draft conversion goal columns
    to handle the query params because it's a draft column */
    actionToUrl(({ values }) => ({
        setQuery: () => {
            const marketingQuery = values.query?.source as MarketingAnalyticsTableQuery | undefined
            const searchParams = new URLSearchParams(window.location.search)
            const selectArray =
                marketingQuery?.select?.filter(
                    (column: string) => !isDraftConversionGoalColumn(column, values.draftConversionGoal)
                ) || []

            if (marketingQuery?.orderBy && marketingQuery?.orderBy.length > 0) {
                const [column, direction] = marketingQuery.orderBy[0]
                if (selectArray.includes(column)) {
                    searchParams.set('order_column', column)
                    searchParams.set('order_direction', direction)
                }
            } else {
                searchParams.delete('order_column')
                searchParams.delete('order_direction')
            }

            if (selectArray.length > 0) {
                searchParams.set('select', selectArray.join(','))
            } else {
                searchParams.delete('select')
            }

            if (values.query?.pinnedColumns && values.query?.pinnedColumns.length > 0) {
                searchParams.set('pinned_columns', values.query.pinnedColumns.join(','))
            } else {
                searchParams.delete('pinned_columns')
            }

            return [window.location.pathname, searchParams.toString()]
        },
    })),
    urlToAction(({ actions, values }) => ({
        '*': (_, searchParams) => {
            const marketingQuery = values.query?.source as MarketingAnalyticsTableQuery | undefined

            let newSelect = marketingQuery?.select || []
            const selectParam = searchParams.select
            if (selectParam) {
                const selectArray: string[] = Array.from(new Set(selectParam.split(',')))
                newSelect = selectArray.filter(
                    (column: string) => !isDraftConversionGoalColumn(column, values.draftConversionGoal)
                )

                actions.setQuery({
                    ...values.query,
                    source: {
                        ...values.query?.source,
                        select: newSelect,
                    },
                } as DataTableNode)
            }

            let newOrderBy: MarketingAnalyticsOrderBy[] = []
            const orderColumn = searchParams.order_column
            const orderDirection = searchParams.order_direction as 'ASC' | 'DESC' | undefined

            if (orderColumn && orderDirection && newSelect.includes(orderColumn)) {
                newOrderBy = createMarketingAnalyticsOrderBy(orderColumn, orderDirection)
                actions.setQuery({
                    ...values.query,
                    source: {
                        ...values.query?.source,
                        orderBy: newOrderBy,
                    },
                } as DataTableNode)
            }

            if (searchParams.pinned_columns) {
                const pinnedColumns = searchParams.pinned_columns.split(',')
                actions.setQuery({
                    ...values.query,
                    pinnedColumns: pinnedColumns,
                } as DataTableNode)
            }
        },
    })),
    listeners(({ actions, values }) => ({
        setDraftConversionGoal: ({ goal }: { goal: ConversionGoalFilter | null }) => {
            if (!goal) {
                const marketingQuery = values.query?.source as MarketingAnalyticsTableQuery | undefined
                // If the dynamic conversion goal is removed, we clear the order by
                if (marketingQuery?.orderBy && !values.defaultColumns.includes(marketingQuery?.orderBy[0][0])) {
                    actions.setQuery({
                        ...values.query,
                        source: {
                            ...values.query?.source,
                            orderBy: undefined,
                        },
                    } as DataTableNode)
                }
            }
        },
        setQuery: ({ query }: { query: DataTableNode }) => {
            // If we remove one column from the draft conversion goal, we clear the draft conversion goal completely
            const marketingQuery = query.source as MarketingAnalyticsTableQuery | undefined
            const selectArray =
                marketingQuery?.select?.filter((column: string) =>
                    isDraftConversionGoalColumn(column, values.draftConversionGoal)
                ) || []

            if (selectArray.length === 1) {
                actions.setDraftConversionGoal(null)
            }
        },
    })),
])
