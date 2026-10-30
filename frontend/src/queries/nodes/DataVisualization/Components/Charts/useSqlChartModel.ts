import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import {
    type ChartTheme,
    type Series,
    type TooltipConfig,
    type XAxisConfig,
    type ChartMargins,
    type YAxisConfig,
    type ValueDomain,
    type BarsConfig,
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
import { resolveSQLReferenceLines } from './sqlReferenceLines'

export interface SqlChartModel<TConfig> {
    series: Series<SqlLineSeriesMeta>[]
    labels: string[]
    theme: ChartTheme
    config: TConfig
}

export function useSqlChartModel<
    TConfig extends {
        tooltip?: TooltipConfig
        xAxis?: XAxisConfig
        yAxis?: YAxisConfig | YAxisConfig[]
        valueDomain?: ValueDomain
        bars?: BarsConfig
        margins?: Partial<ChartMargins>
    },
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
        labelFormatter,
        xAxis,
        margins,
        valueDomain,
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
        () => (ySeriesData ? buildSeries(ySeriesData, visualizationType, chartSettings.showValuesOnSeries) : []),
        [ySeriesData, visualizationType, chartSettings.showValuesOnSeries]
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
            goalLines: resolveSQLReferenceLines(
                goalLines,
                series,
                visualizationType === ChartDisplayType.ActionsStackedBar && chartSettings.stackBars100
            ),
            visualizationType,
            ySeriesData,
            series,
            legendRenderItem,
            embedded,
        })
        const formatLabel = labelFormatter
            ? (value: string): string => {
                  const raw = visualizationType === ChartDisplayType.ActionsBarValue ? xData.data[Number(value)] : value
                  const label = labelFormatter(raw)
                  return label === raw ? (config.tooltip?.labelFormatter?.(value) ?? label) : label
              }
            : undefined
        return {
            ...config,
            ...(valueDomain
                ? {
                      valueDomain,
                      ...(visualizationType === ChartDisplayType.ActionsBarValue
                          ? {
                                bars: {
                                    ...config.bars,
                                    valueDomain: {
                                        ...config.bars?.valueDomain,
                                        ...valueDomain,
                                        include: [
                                            ...(config.bars?.valueDomain?.include ?? []),
                                            ...(valueDomain.include ?? []),
                                        ],
                                    },
                                },
                            }
                          : {}),
                      yAxis: Array.isArray(config.yAxis)
                          ? config.yAxis.map((axis, index) =>
                                index === 0 ? { ...axis, min: valueDomain.min, max: valueDomain.max } : axis
                            )
                          : { ...config.yAxis, min: valueDomain.min, max: valueDomain.max },
                  }
                : {}),
            ...(formatLabel && visualizationType === ChartDisplayType.ActionsBarValue
                ? { xTickFormatter: formatLabel }
                : {}),
            xAxis: { ...config.xAxis, ...xAxis },
            margins: { ...config.margins, ...margins },
            tooltip: {
                ...config.tooltip,
                resolveClickToNearestSeries: directPointClick,
                ...(formatLabel ? { labelFormatter: formatLabel } : {}),
            },
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
        labelFormatter,
        xAxis,
        margins,
        valueDomain,
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
