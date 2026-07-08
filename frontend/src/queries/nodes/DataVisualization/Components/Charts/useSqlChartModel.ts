import { useValues } from 'kea'
import { useCallback, useEffect, useMemo } from 'react'

import { type ChartTheme, type DateRangeZoomData, type Series } from '@posthog/quill-charts'

import { useChartTheme, useChartConfig } from 'lib/charts/hooks'
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

/** Adapts the host's `onDateRangeZoom(dateFrom, dateTo)` to the quill chart's drag callback, or
 *  returns undefined when zooming doesn't apply — no handler, or a non-date x-axis (arbitrary
 *  string/number x values stay inert). */
export function useSqlDateRangeZoom({
    xData,
    onDateRangeZoom,
}: Pick<LineGraphProps, 'xData' | 'onDateRangeZoom'>): ((data: DateRangeZoomData) => void) | undefined {
    const handler = useCallback(
        ({ startLabel, endLabel }: DateRangeZoomData) => {
            // SQL results aren't guaranteed chronological, so order the pair before applying.
            const [dateFrom, dateTo] = startLabel <= endLabel ? [startLabel, endLabel] : [endLabel, startLabel]
            onDateRangeZoom?.(dateFrom, dateTo)
        },
        [onDateRangeZoom]
    )

    const xTypeName = xData?.column.type.name
    const zoomEnabled = !!onDateRangeZoom && (xTypeName === 'DATE' || xTypeName === 'DATETIME')
    return zoomEnabled ? handler : undefined
}
