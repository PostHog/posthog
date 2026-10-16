import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { buildBIRowsQuery } from './biEditorTypes'

export function buildBISourcePreview(
    worksheet: BIVisualizationNode,
    filtered: boolean,
    limit: number
): DataVisualizationNode | null {
    const config = filtered
        ? worksheet.config
        : {
              ...worksheet.config,
              filters: [],
              rowFilterGroup: undefined,
              dateRange: { date_from: 'all' },
              comparisonPeriod: undefined,
          }
    const source = buildBIRowsQuery(config, false, Math.min(10000, Math.max(1000, limit)))
    if (!source) {
        return null
    }
    return {
        kind: NodeKind.DataVisualizationNode,
        display: ChartDisplayType.ActionsTable,
        source: {
            ...source,
            variables: worksheet.source.variables,
            filters: filtered ? { ...source.filters, ...worksheet.source.filters } : source.filters,
        },
    }
}
