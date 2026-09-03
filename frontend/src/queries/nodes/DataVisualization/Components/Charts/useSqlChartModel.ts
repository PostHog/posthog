import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { type ChartTheme, type Series, type TooltipConfig } from '@posthog/quill-charts'

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

const SQL_CHART_INSPECT_TOOLTIP_FOOTER = 'Click to inspect persons'

export interface SqlChartModel<TConfig> {
    series: Series<SqlLineSeriesMeta>[]
    labels: string[]
    theme: ChartTheme
    config: TConfig
}

export function useSqlChartModel<TConfig extends { tooltip?: TooltipConfig }>(
    { xData, yData, visualizationType, chartSettings, dashboardId, goalLines, onPointClick }: SqlChartProps,
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
            legendRenderItem,
        })
        if (onPointClick) {
            config.tooltip = { ...config.tooltip, footer: SQL_CHART_INSPECT_TOOLTIP_FOOTER }
        }
        return config
    }, [
        xData,
        chartSettings,
        timezone,
        goalLines,
        visualizationType,
        buildConfig,
        ySeriesData,
        legendRenderItem,
        onPointClick,
    ])

    if (!xData || !ySeriesData || series.length === 0 || !config) {
        return null
    }

    return { series, labels: xData.data, theme, config }
}
