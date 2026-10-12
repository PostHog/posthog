import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import {
    type ChartTheme,
    type Series,
    type TooltipConfig,
    type XAxisConfig,
    type ChartMargins,
} from '@posthog/quill-charts'

import { useChartTheme, useChartConfig } from 'lib/charts/hooks'
import { useChartLegendSeriesMenu } from 'lib/components/ChartLegendSeriesMenu/useChartLegendSeriesMenu'
import { teamLogic } from 'scenes/teamLogic'

import { ChartDisplayType } from '~/types'

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

export function useSqlChartModel<
    TConfig extends { tooltip?: TooltipConfig; xAxis?: XAxisConfig; margins?: Partial<ChartMargins> },
>(
    {
        xData,
        yData,
        visualizationType,
        chartSettings,
        dashboardId,
        goalLines,
        embedded,
        directPointClick,
        xAxis,
        margins,
    }: SqlChartProps,
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

    const config = useChartConfig(() => {
        if (!xData) {
            return undefined
        }
        const config = buildConfig({
            xData,
            chartSettings,
            timezone,
            goalLines,
            visualizationType,
            ySeriesData,
            series,
            legendRenderItem,
            embedded,
        })
        return {
            ...config,
            xAxis: { ...config.xAxis, ...xAxis },
            margins: { ...config.margins, ...margins },
            tooltip: { ...config.tooltip, resolveClickToNearestSeries: directPointClick },
        }
    }, [
        xData,
        chartSettings,
        timezone,
        goalLines,
        visualizationType,
        buildConfig,
        ySeriesData,
        series,
        legendRenderItem,
        embedded,
        directPointClick,
        xAxis,
        margins,
    ])

    const labels = useMemo(
        () =>
            visualizationType === ChartDisplayType.ActionsBarValue
                ? (xData?.data.map((_, index) => String(index)) ?? [])
                : (xData?.data ?? []),
        [visualizationType, xData]
    )

    if (!xData || !ySeriesData || series.length === 0 || !config) {
        return null
    }

    return { series, labels, theme, config }
}
