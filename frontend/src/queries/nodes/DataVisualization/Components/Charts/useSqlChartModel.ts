import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { type ChartTheme, type Series } from '@posthog/quill-charts'

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
}

/**
 * Shared plumbing for the quill SQL charts — series, theme, max-series warning. The per-chart-type
 * config (line vs bar, which are different types) comes from `buildConfig`; line builders ignore the
 * extra `visualizationType` field.
 */
export function useSqlChartModel<TConfig>(
    { xData, yData, visualizationType, chartSettings, dashboardId, goalLines }: LineGraphProps,
    buildConfig: (args: BuildBarConfigArgs) => TConfig
): SqlChartModel<TConfig> | null {
    const { timezone } = useValues(teamLogic)
    const { isDarkModeOn } = useValues(themeLogic)

    useEffect(() => {
        if (exceedsMaxSeries(yData, dashboardId)) {
            warnTooManySeries(yData!.length)
        }
    }, [yData, dashboardId])

    const ySeriesData = useMemo(() => capYSeriesData(yData), [yData])

    const series = useMemo(
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

    if (!xData || !ySeriesData || series.length === 0 || !config) {
        return null
    }

    return { series, labels: xData.data, theme, config }
}
