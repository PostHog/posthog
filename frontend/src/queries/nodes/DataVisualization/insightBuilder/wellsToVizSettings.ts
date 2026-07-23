import { ChartAxis, ChartSettings, InsightBuilderConfig } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { measureLabel } from './builderLabels'
import { CompiledBuilderQuery } from './compileBuilderQuery'

const SERIES_BREAKDOWN_DISPLAYS: ChartDisplayType[] = [
    ChartDisplayType.ActionsLineGraph,
    ChartDisplayType.ActionsBar,
    ChartDisplayType.ActionsStackedBar,
    ChartDisplayType.ActionsAreaGraph,
]

/**
 * Map compiled wells onto the visualization config the chart renderers consume.
 * Per-series formatting the user set previously is preserved by alias so it
 * survives recompiles; everything positional (axes, breakdown, heatmap columns)
 * is recomputed from the wells.
 */
export function mapWellsToChartSettings(
    prev: ChartSettings | undefined,
    compiled: CompiledBuilderQuery,
    display: ChartDisplayType,
    config: InsightBuilderConfig
): ChartSettings {
    const prevYAxisByColumn: Record<string, ChartAxis> = {}
    for (const axis of prev?.yAxis ?? []) {
        prevYAxisByColumn[axis.column] = axis
    }

    const yAxis: ChartAxis[] = compiled.valueAliases.map((alias, index) => {
        const previous = prevYAxisByColumn[alias]
        // Label the series the way the well reads (e.g. "Count of rows", "Sum of amount") rather
        // than exposing the machine alias like count_rows
        const measure = config.values[index]
        const label = measure?.label ?? (measure ? measureLabel(measure) : undefined)
        const settings = {
            ...previous?.settings,
            ...(label ? { display: { ...previous?.settings?.display, label } } : {}),
        }
        return Object.keys(settings).length > 0 ? { column: alias, settings } : { column: alias }
    })

    // Consistent across charts: Columns is the x-axis, Rows is the series breakdown
    const xAxisColumn = compiled.columnAliases[0]
    const breakdownColumn = compiled.rowAliases[0]
    const next: ChartSettings = {
        ...prev,
        xAxis: xAxisColumn
            ? {
                  column: xAxisColumn,
                  ...(prev?.xAxis?.column === xAxisColumn && prev.xAxis.settings
                      ? { settings: prev.xAxis.settings }
                      : {}),
              }
            : undefined,
        yAxis,
        seriesBreakdownColumn: SERIES_BREAKDOWN_DISPLAYS.includes(display) ? (breakdownColumn ?? null) : null,
    }

    if (display === ChartDisplayType.TwoDimensionalHeatmap) {
        next.heatmap = {
            ...prev?.heatmap,
            yAxisColumn: compiled.rowAliases[0],
            xAxisColumn: compiled.columnAliases[0],
            valueColumn: compiled.valueAliases[0],
        }
    }

    return next
}
