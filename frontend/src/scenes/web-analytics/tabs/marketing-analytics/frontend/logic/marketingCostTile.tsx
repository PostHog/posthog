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
