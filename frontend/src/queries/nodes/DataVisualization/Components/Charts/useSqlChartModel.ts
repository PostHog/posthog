import { useValues } from 'kea'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { type ChartTheme, type LegendItem, type Series, legendItemsFromSeries } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { LineGraphProps } from './LineGraph'
import {
    type BuildBarConfigArgs,
    buildSeries,
    capYSeriesData,
    exceedsMaxSeries,
    warnTooManySeries,
} from './sqlLineGraphAdapter'

export interface SqlChartModel<TConfig> {
    series: Series[]
    labels: string[]
    theme: ChartTheme
    config: TConfig
    legendItems: LegendItem[]
    hiddenKeys: string[]
    toggleSeries: (key: string) => void
}

/**
 * Shared model for the quill SQL charts. Builds series, theme, legend, and hidden-series state once;
 * the per-chart-type config (line vs bar) comes from {@link buildConfig}. `BuildBarConfigArgs` is the
 * superset arg shape — line builders simply ignore the extra `visualizationType` field.
 */
export function useSqlChartModel<TConfig>(
    { xData, yData, visualizationType, chartSettings, dashboardId, goalLines }: LineGraphProps,
    buildConfig: (args: BuildBarConfigArgs) => TConfig | undefined
): SqlChartModel<TConfig> | null {
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
        () => (xData ? buildConfig({ xData, chartSettings, timezone, goalLines, visualizationType }) : undefined),
        [xData, chartSettings, timezone, goalLines, visualizationType, buildConfig]
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
