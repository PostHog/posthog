import { CurrencyCode, DataWarehouseNode, NodeKind } from '~/queries/schema/schema-general'
import { PropertyMathType } from '~/types'

import { ExternalTable } from './marketingAnalyticsLogic'
import { validColumnsForTiles } from './utils'

export const externalAdsCostTile = (
    table: ExternalTable,
    baseCurrency: string,
    tileColumnSelection: validColumnsForTiles
): DataWarehouseNode | null => {
    if (!table.source_map || !table.source_map.date || !table.source_map.cost) {
        return null
    }

    // Handle ROAS (Return on Ad Spend) - calculated as conversion_value / cost
    if (tileColumnSelection === 'roas') {
        const costColumn = table.source_map.cost
        const conversionValueColumn = table.source_map.reported_conversion_value

        // If no conversion value column mapped, ROAS cannot be calculated
        if (!conversionValueColumn) {
            return null
        }

        const mathHogql = `SUM(ifNull(toFloat(${conversionValueColumn}), 0)) / nullIf(SUM(toFloat(${costColumn})), 0)`

        return {
            kind: NodeKind.DataWarehouseNode,
            id: table.id,
            name: table.schema_name,
            custom_name: `${table.schema_name} roas`,
            id_field: 'id',
            distinct_id_field: 'id',
            timestamp_field: table.source_map.date,
            table_name: table.name,
            dw_source_type: table.dw_source_type,
            math: 'hogql' as any,
            math_hogql: mathHogql,
        }
    }

    const column = table.source_map[tileColumnSelection]
    if (!column) {
        return null
    }
    return {
        kind: NodeKind.DataWarehouseNode,
        id: table.id,
        name: table.schema_name,
        custom_name: `${table.schema_name} ${tileColumnSelection}`,
        id_field: 'id',
        distinct_id_field: 'id',
        timestamp_field: table.source_map.date,
        table_name: table.name,
        dw_source_type: table.dw_source_type,
        math: PropertyMathType.Sum,
        math_property: column,
        math_property_revenue_currency: {
            static: (table.source_map.currency || baseCurrency) as CurrencyCode,
        },
    }
}
