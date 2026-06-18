import { useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'

import {
    type ChartTheme,
    type LegendItem,
    type Series,
    type TimeSeriesLineChartConfig,
    legendItemsFromSeries,
} from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { LineGraphProps } from './LineGraph'
import {
    buildLineChartConfig,
    buildSeries,
    capYSeriesData,
    exceedsMaxSeries,
    warnTooManySeries,
} from './sqlLineGraphAdapter'

export interface SqlLineGraphModel {
    series: Series[]
    labels: string[]
    theme: ChartTheme
    config: TimeSeriesLineChartConfig
    legendItems: LegendItem[]
    hiddenKeys: string[]
    toggleSeries: (key: string) => void
}

export function useSqlLineGraph({
    xData,
    yData,
    visualizationType,
    chartSettings,
    dashboardId,
    goalLines,
}: LineGraphProps): SqlLineGraphModel | null {
    const { timezone } = useValues(teamLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const [hiddenKeys, setHiddenKeys] = useState<string[]>([])

    // Fire the cap warning as a side effect — capYSeriesData itself stays pure.
    useEffect(() => {
        if (exceedsMaxSeries(yData, dashboardId)) {
            warnTooManySeries(yData!.length)
        }
    }, [yData, dashboardId])

    const ySeriesData = useMemo(() => capYSeriesData(yData), [yData])

    const allSeries = useMemo(
        () => (ySeriesData ? buildSeries(ySeriesData, visualizationType) : []),
        [ySeriesData, visualizationType]
    )

    // buildTheme reads CSS vars at call time; re-derive when the user toggles light/dark.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])

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
