import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { isNotNil } from 'lib/utils'

import {
    DatabaseSchemaDataWarehouseTable,
    SourceMap,
    ConversionGoalFilter,
    DataTableNode,
    NodeKind,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsHelperForColumnNames,
} from '~/queries/schema/schema-general'
import { DataWarehouseSettingsTab, ExternalDataSource } from '~/types'

import type { marketingAnalyticsTableLogicType } from './marketingAnalyticsTableLogicType'
import { marketingAnalyticsLogic } from './marketingAnalyticsLogic'

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
        values: [marketingAnalyticsLogic, ['conversion_goals']],
        actions: [marketingAnalyticsLogic, ['setDynamicConversionGoal']],
    })),
    actions({
        setSelectedColumns: (defaultColumns: string[]) => ({ defaultColumns }),
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
    listeners(({ actions, values }) => ({
        setQuery: () => {
            if (values.query?.source.kind === NodeKind.MarketingAnalyticsTableQuery) {
                const source = values.query.source
                actions.setSelectedColumns(source.select || [])
            }
        },
    })),
])
