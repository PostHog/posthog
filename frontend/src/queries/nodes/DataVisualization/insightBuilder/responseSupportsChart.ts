import { DataVisualizationNode } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

/**
 * Whether the response can feed the node's chart at all — false when the chart's series columns
 * are entirely absent from the response, i.e. the results answer a different query (e.g. the raw
 * base query ran while the chart expects compiled aliases). Partial overlap counts as supported:
 * recompiles keep existing aliases stable, so a transitional response can still draw.
 */
export function responseSupportsChart(
    query: DataVisualizationNode,
    responseColumns: string[] | undefined | null
): boolean {
    if (!responseColumns || responseColumns.length === 0) {
        return true // Nothing loaded (yet) — absence of results is not a mismatch
    }

    const display = query.display
    if (!display || display === ChartDisplayType.Auto || display === ChartDisplayType.ActionsTable) {
        return true // Tables render whatever came back
    }

    const available = new Set(responseColumns)

    if (display === ChartDisplayType.TwoDimensionalHeatmap) {
        const valueColumn = query.chartSettings?.heatmap?.valueColumn
        return !valueColumn || available.has(valueColumn)
    }

    const yColumns = (query.chartSettings?.yAxis ?? []).map((axis) => axis.column).filter(Boolean)
    if (yColumns.length === 0) {
        return true // No series configured yet — nothing to mismatch against
    }
    return yColumns.some((column) => available.has(column))
}
