import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { type ChartTheme, type DateRangeZoomData, type Series } from '@posthog/quill-charts'

import { useChartTheme, useChartConfig, useDateRangeZoom } from 'lib/charts/hooks'
import { teamLogic } from 'scenes/teamLogic'

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

export function useSqlChartModel<TConfig extends object>(
    { xData, yData, visualizationType, chartSettings, dashboardId, goalLines }: LineGraphProps,
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
                  })
                : undefined,
        [xData, chartSettings, timezone, goalLines, visualizationType, buildConfig, ySeriesData]
    )

    if (!xData || !ySeriesData || series.length === 0 || !config) {
        return null
    }

    return { series, labels: xData.data, theme, config }
}

/** `useDateRangeZoom` with the SQL-specific gate: only a date/datetime x-axis maps to a date
 *  range — arbitrary string/number x values stay inert. */
export function useSqlDateRangeZoom({
    xData,
    onDateRangeZoom,
}: Pick<LineGraphProps, 'xData' | 'onDateRangeZoom'>): ((data: DateRangeZoomData) => void) | undefined {
    const xTypeName = xData?.column.type.name
    const isDateAxis = xTypeName === 'DATE' || xTypeName === 'DATETIME'
    return useDateRangeZoom(isDateAxis ? xData?.data : undefined, onDateRangeZoom)
}
