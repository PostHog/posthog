import { CurrencyCode, DataWarehouseNode, NodeKind } from '~/queries/schema/schema-general'
import { PropertyMathType } from '~/types'

import { ExternalTable, NativeSource } from './marketingAnalyticsLogic'
import { COST_MICROS_MULTIPLIER, GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME } from './utils'

export const googleAdsCostTile = (source: NativeSource): DataWarehouseNode | null => {
    const table = source.tables.find((t) => t.name.split('.').pop() === GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME)
    if (!table) {
        return null
    }

    return {
        kind: NodeKind.DataWarehouseNode,
        id: table.id,
        name: 'google',
        custom_name: `${table.name} Cost`,
        id_field: 'id',
        distinct_id_field: 'id',
        timestamp_field: 'segments_date',
        table_name: table.name,
        math: PropertyMathType.Sum,
        math_property: 'metrics_cost_micros',
        math_property_revenue_currency: { static: CurrencyCode.USD },
        math_multiplier: COST_MICROS_MULTIPLIER,
    }
}

export const externalAdsCostTile = (table: ExternalTable, baseCurrency: string): DataWarehouseNode | null => {
    if (!table.source_map || !table.source_map.date || !table.source_map.total_cost) {
        return null
    }

    return {
        kind: NodeKind.DataWarehouseNode,
        id: table.id,
        name: table.schema_name,
        custom_name: `${table.schema_name} Cost`,
        id_field: 'id',
        distinct_id_field: 'id',
        timestamp_field: table.source_map.date,
        table_name: table.name,
        math: PropertyMathType.Sum,
        math_property: table.source_map.total_cost,
        math_property_revenue_currency: {
            static: (table.source_map.currency || baseCurrency) as CurrencyCode,
        },
    }
}
