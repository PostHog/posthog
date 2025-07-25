import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { isNotNil } from 'lib/utils'

import {
    DatabaseSchemaDataWarehouseTable,
    SourceMap,
    ConversionGoalFilter,
    DataTableNode,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsHelperForColumnNames,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'
import { DataWarehouseSettingsTab, ExternalDataSource } from '~/types'

import type { marketingAnalyticsTableLogicType } from './marketingAnalyticsTableLogicType'
import { marketingAnalyticsLogic } from './marketingAnalyticsLogic'
import { actionToUrl, urlToAction } from 'kea-router'
import { isDraftConversionGoalColumn } from './utils'

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
    }),
    /* Both in actionToUrl and urlToAction we need to filter out the draft conversion goal columns
    to handle the query params because it's a draft column */
    actionToUrl(({ values }) => ({
        setQuery: () => {
            const typedQuery = values.query?.source as MarketingAnalyticsTableQuery | undefined
            const searchParams = new URLSearchParams(window.location.search)
            const selectArray = typedQuery?.select?.filter(
                (column: string) => !isDraftConversionGoalColumn(column, values.draftConversionGoal)
            )

            if (typedQuery?.orderBy && typedQuery?.orderBy.length > 0) {
                const [column, direction] = typedQuery.orderBy[0]
                if (selectArray && selectArray.includes(column)) {
                    searchParams.set('order_column', column)
                    searchParams.set('order_direction', direction)
                }
            } else {
                searchParams.delete('order_column')
                searchParams.delete('order_direction')
            }

            if (selectArray && selectArray.length > 0) {
                searchParams.set('select', selectArray.join(','))
            } else {
                searchParams.delete('select')
            }

            return [window.location.pathname, searchParams.toString()]
        },
    })),
    urlToAction(({ actions, values }) => ({
        '*': (_, searchParams) => {
            const typedQuery = values.query?.source as MarketingAnalyticsTableQuery | undefined

            let newSelect = typedQuery?.select || []
            const selectParam = searchParams.select
            if (selectParam) {
                const selectArray = selectParam.split(',')
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

            let newOrderBy: [string, 'ASC' | 'DESC'][] = []
            const orderColumn = searchParams.order_column
            const orderDirection = searchParams.order_direction as 'ASC' | 'DESC' | undefined

            if (orderColumn && orderDirection && newSelect.includes(orderColumn)) {
                newOrderBy = [[orderColumn, orderDirection]]
                actions.setQuery({
                    ...values.query,
                    source: {
                        ...values.query?.source,
                        orderBy: newOrderBy,
                    },
                } as DataTableNode)
            }
        },
    })),
    listeners(({ actions, values }) => ({
        setDraftConversionGoal: ({ goal }: { goal: ConversionGoalFilter | null }) => {
            if (!goal) {
                const typedQuery = values.query?.source as MarketingAnalyticsTableQuery | undefined
                if (typedQuery?.orderBy && !values.defaultColumns.includes(typedQuery?.orderBy[0][0])) {
                    typedQuery.orderBy = []
                    actions.setQuery({
                        ...values.query,
                        source: {
                            ...values.query?.source,
                            orderBy: typedQuery.orderBy,
                        },
                    } as DataTableNode)
                }
            }
        },
    })),
])
