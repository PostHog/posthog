import clsx from 'clsx'
import { useValues } from 'kea'
import { useMemo, useState } from 'react'

import { Legend, TimeSeriesLineChart, TooltipSurface, TooltipSwatch, legendItemsFromSeries } from '@posthog/quill-charts'

import { teamLogic } from 'scenes/teamLogic'

import { formatDataWithSettings } from '../../dataVisualizationLogic'
import { LineGraphProps } from './LineGraph'
import {
    SqlLineSeriesMeta,
    buildChartTheme,
    buildLineChartConfig,
    buildSeries,
    capYSeriesData,
} from './sqlLineGraphAdapter'

/**
 * SQL line/area graph rendered via @posthog/quill-charts, gated behind the `data-viz-quill-charts`
 * flag (see {@link LineGraph}). Handles line, area, and dual y-axis charts; the dispatcher in
 * `LineGraph` falls back to the legacy chart.js path for anything not yet ported.
 */
export const SqlLineGraph = ({
    xData,
    yData,
    presetChartHeight,
    visualizationType,
    chartSettings,
    dashboardId,
    className,
}: LineGraphProps): JSX.Element | null => {
    const { timezone } = useValues(teamLogic)

    // Series keys hidden by clicking the legend, mirroring chart.js's click-to-toggle legend.
    const [hiddenKeys, setHiddenKeys] = useState<string[]>([])

    const ySeriesData = useMemo(() => capYSeriesData(yData, dashboardId), [yData, dashboardId])

    const series = useMemo(
        () => (ySeriesData ? buildSeries(ySeriesData, visualizationType) : []),
        [ySeriesData, visualizationType]
    )

    const theme = useMemo(() => buildChartTheme(), [])

    const config = useMemo(
        () => (xData ? buildLineChartConfig({ xData, chartSettings, timezone }) : undefined),
        [xData, chartSettings, timezone]
    )

    const showLegend = chartSettings.showLegend ?? false
    const legendItems = useMemo(
        () => (showLegend ? legendItemsFromSeries(series, theme) : []),
        [showLegend, series, theme]
    )

    // Exclude hidden series from rendering/scale/hit-testing; the legend keeps showing them dimmed.
    const visibleSeries = useMemo(() => {
        if (hiddenKeys.length === 0) {
            return series
        }
        const hidden = new Set(hiddenKeys)
        return series.map((s) =>
            hidden.has(s.key) ? { ...s, visibility: { ...s.visibility, excluded: true } } : s
        )
    }, [series, hiddenKeys])

    if (!xData || !ySeriesData || series.length === 0) {
        return null
    }

    const toggleSeries = (key: string): void =>
        setHiddenKeys((keys) => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key]))

    return (
        <div
            className={clsx(className, 'rounded bg-surface-primary w-full grow relative overflow-hidden flex flex-col', {
                'h-[60vh]': presetChartHeight,
                'h-full': !presetChartHeight,
            })}
        >
            {showLegend && legendItems.length > 0 && (
                <Legend
                    items={legendItems}
                    hiddenKeys={hiddenKeys}
                    onItemClick={toggleSeries}
                    className="flex-none px-3 pt-2"
                />
            )}
            <div className="flex-1 min-h-0">
                <TimeSeriesLineChart<SqlLineSeriesMeta>
                    series={visibleSeries}
                    labels={xData.data}
                    theme={theme}
                    config={config}
                    tooltip={(ctx) => (
                        // TODO(PR2): port the full LemonTable/InsightLabel tooltip (sorted rows, total
                        //   row, ribbon colors). This is a minimal label + per-series value placeholder.
                        <TooltipSurface>
                            <div className="font-semibold mb-1">{ctx.label}</div>
                            {ctx.seriesData.map((point) => (
                                <div key={point.series.key} className="flex items-center gap-2">
                                    <TooltipSwatch color={point.color} />
                                    <span className="flex-1">{point.series.label}</span>
                                    <span className="text-right">
                                        {String(
                                            formatDataWithSettings(point.value, point.series.meta?.settings) ??
                                                point.value
                                        )}
                                    </span>
                                </div>
                            ))}
                        </TooltipSurface>
                    )}
                />
            </div>
        </div>
    )
}
