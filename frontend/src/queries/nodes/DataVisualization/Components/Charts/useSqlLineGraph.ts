import { useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'

import {
    type ChartTheme,
    type LegendItem,
    type Series,
    type TimeSeriesLineChartConfig,
    legendItemsFromSeries,
} from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { teamLogic } from 'scenes/teamLogic'

import { LineGraphProps } from './LineGraph'
import { SqlLineSeriesMeta, buildLineChartConfig, buildSeries, capYSeriesData } from './sqlLineGraphAdapter'

export interface SqlLineGraphModel {
    series: Series<SqlLineSeriesMeta>[]
    labels: string[]
    theme: ChartTheme
    config: TimeSeriesLineChartConfig
    legendItems: LegendItem[]
    hiddenKeys: string[]
    toggleSeries: (key: string) => void
}

/** Builds everything the {@link SqlLineGraph} component renders, or null when there's nothing to draw. */
export function useSqlLineGraph({
    xData,
    yData,
    visualizationType,
    chartSettings,
    dashboardId,
    goalLines,
}: LineGraphProps): SqlLineGraphModel | null {
    const { timezone } = useValues(teamLogic)
    const [hiddenKeys, setHiddenKeys] = useState<string[]>([])

    const ySeriesData = useMemo(() => capYSeriesData(yData, dashboardId), [yData, dashboardId])

    const allSeries = useMemo(
        () => (ySeriesData ? buildSeries(ySeriesData, visualizationType) : []),
        [ySeriesData, visualizationType]
    )

    const theme = useMemo(() => buildTheme(), [])

    const config = useMemo(
        () => (xData ? buildLineChartConfig({ xData, chartSettings, timezone, goalLines }) : undefined),
        [xData, chartSettings, timezone, goalLines]
    )

    const showLegend = chartSettings.showLegend ?? false
    const legendItems = useMemo(
        () => (showLegend ? legendItemsFromSeries(allSeries, theme) : []),
        [showLegend, allSeries, theme]
    )

    // Hidden series are excluded from rendering/scale/hit-testing; the legend still shows them dimmed.
    const series = useMemo(() => {
        if (hiddenKeys.length === 0) {
            return allSeries
        }
        const hidden = new Set(hiddenKeys)
        return allSeries.map((s) => (hidden.has(s.key) ? { ...s, visibility: { ...s.visibility, excluded: true } } : s))
    }, [allSeries, hiddenKeys])

    const toggleSeries = useCallback(
        (key: string) => setHiddenKeys((keys) => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key])),
        []
    )

    if (!xData || !ySeriesData || allSeries.length === 0 || !config) {
        return null
    }

    return { series, labels: xData.data, theme, config, legendItems, hiddenKeys, toggleSeries }
}
