import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { type ChartTheme, type Series } from '@posthog/quill-charts'

import { useChartTheme, useChartConfig } from 'lib/charts/hooks'
import { useChartLegendSeriesMenu } from 'lib/components/ChartLegendSeriesMenu/useChartLegendSeriesMenu'
import { teamLogic } from 'scenes/teamLogic'

import { SqlChartProps } from './SqlChart'
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

export function useSqlChartModel<TConfig extends object>(
    { xData, yData, visualizationType, chartSettings, dashboardId, goalLines }: SqlChartProps,
    buildConfig: (args: BuildBarConfigArgs) => TConfig
): SqlChartModel<TConfig> | null {
    const { timezone } = useValues(teamLogic)

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

    const theme = useChartTheme()

    const legendRenderItem = useChartLegendSeriesMenu({ surface: 'sql', seriesCount: series.length })

    const config = useChartConfig(
        () =>
            xData
                ? buildConfig({
                      xData,
                      chartSettings,
                      timezone,
                      goalLines,
                      visualizationType,
                      ySeriesData,
                      legendRenderItem,
                  })
                : undefined,
        [xData, chartSettings, timezone, goalLines, visualizationType, buildConfig, ySeriesData, legendRenderItem]
    )

    if (!xData || !ySeriesData || series.length === 0 || !config) {
        return null
    }

    return { series, labels: xData.data, theme, config }
}
