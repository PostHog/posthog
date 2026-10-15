import { useCallback, useMemo, useState } from 'react'

import type { ChartLegendConfig, ChartTheme, Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { useChartLegendSeriesMenu } from 'lib/components/ChartLegendSeriesMenu/useChartLegendSeriesMenu'

import { ChartSettings } from '~/queries/schema/schema-general'

import { AxisSeriesSettings } from '../../dataVisualizationLogic'
import { SqlChartProps } from './SqlChart'
import { formatSqlSeriesValue } from './sqlLineGraphAdapter'
import { buildPieSeries, buildPieSlices, showsLegendByDefault, showsPieTotal } from './sqlPieGraphAdapter'

export interface SqlPartOfWholeChart {
    theme: ChartTheme
    series: Series[]
    legendConfig: ChartLegendConfig
    total: number
    showTotal: boolean
    formattingSettings: AxisSeriesSettings | undefined
    valueFormatter: (value: number) => string
}

/** The parts, legend, total and formatting a SQL pie, donut or proportion bar shares. */
export function useSqlPartOfWholeChart(
    { xData, yData, chartSettings }: Pick<SqlChartProps, 'xData' | 'yData'> & { chartSettings: ChartSettings },
    isProportionBar: boolean
): SqlPartOfWholeChart {
    const theme = useChartTheme()
    const series = useMemo(() => buildPieSeries(buildPieSlices(xData, yData)), [xData, yData])
    const formattingSettings = yData[0]?.settings

    // Toggled-off slices aren't persisted (SQL insights have nowhere to save them), but the legend
    // is controlled anyway so the total and the tooltip shares track the slices actually drawn.
    const [hiddenKeys, setHiddenKeys] = useState<string[]>([])
    const showLegend = chartSettings.showLegend ?? showsLegendByDefault(isProportionBar, series.length)
    const visibleHiddenKeySet = useMemo(() => new Set(showLegend ? hiddenKeys : []), [showLegend, hiddenKeys])
    const total = useMemo(
        () => series.reduce((sum, s) => (visibleHiddenKeySet.has(s.key) ? sum : sum + (s.data[0] ?? 0)), 0),
        [series, visibleHiddenKeySet]
    )

    const valueFormatter = useCallback(
        (value: number) => formatSqlSeriesValue(value, formattingSettings),
        [formattingSettings]
    )

    const legendRenderItem = useChartLegendSeriesMenu({ surface: 'sql', seriesCount: series.length })

    const legendConfig: ChartLegendConfig = useMemo(
        () => ({
            show: showLegend,
            position: chartSettings.legendPosition ?? (isProportionBar ? 'bottom' : 'right'),
            interactive: true,
            hiddenKeys: showLegend ? hiddenKeys : [],
            onToggleSeries: (key: string) =>
                setHiddenKeys((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key])),
            onSetHiddenSeries: setHiddenKeys,
            renderItem: legendRenderItem,
        }),
        [showLegend, chartSettings.legendPosition, isProportionBar, hiddenKeys, legendRenderItem]
    )

    return {
        theme,
        series,
        legendConfig,
        total,
        showTotal: showsPieTotal(chartSettings, isProportionBar),
        formattingSettings,
        valueFormatter,
    }
}
