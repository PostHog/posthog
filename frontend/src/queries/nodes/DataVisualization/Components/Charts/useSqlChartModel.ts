import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { type ChartTheme, type Series } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { LineGraphProps } from './LineGraph'
import {
    type BuildBarConfigArgs,
    type SqlLineSeriesMeta,
    buildSeries,
    capYSeriesData,
    exceedsMaxSeries,
    warnTooManySeries,
} from './sqlLineGraphAdapter'

export interface SqlChartModel<TConfig> {
    series: Series<SqlLineSeriesMeta>[]
    labels: string[]
    theme: ChartTheme
    config: TConfig
}

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

    // eslint-disable-next-line react-hooks/exhaustive-deps
    const theme = useMemo(() => buildTheme(), [isDarkModeOn])

    const config = useMemo(
        () =>
            xData
                ? buildConfig({
                      xData,
                      chartSettings,
                      timezone,
                      goalLines,
                      visualizationType,
                      ySeriesData,
                  })
                : undefined,
        [xData, chartSettings, timezone, goalLines, visualizationType, buildConfig, ySeriesData]
    )

    if (!xData || !ySeriesData || series.length === 0 || !config) {
        return null
    }

    return { series, labels: xData.data, theme, config }
}
