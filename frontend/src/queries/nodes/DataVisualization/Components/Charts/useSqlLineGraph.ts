import { useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import {
    type ChartTheme,
    type Series,
    type TimeSeriesBarChartConfig,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { teamLogic } from 'scenes/teamLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ChartDisplayType } from '~/types'

import { LineGraphProps } from './LineGraph'
import {
    buildBarChartConfig,
    buildLineChartConfig,
    buildSeries,
    capYSeriesData,
    exceedsMaxSeries,
    warnTooManySeries,
} from './sqlLineGraphAdapter'

interface SqlChartBase {
    series: Series[]
    labels: string[]
    theme: ChartTheme
}

export type SqlChartModel =
    | (SqlChartBase & { chartType: 'line'; config: TimeSeriesLineChartConfig })
    | (SqlChartBase & { chartType: 'bar'; config: TimeSeriesBarChartConfig })

export function useSqlLineGraph({
    xData,
    yData,
    visualizationType,
    chartSettings,
    dashboardId,
    goalLines,
}: LineGraphProps): SqlChartModel | null {
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

    const isBar =
        visualizationType === ChartDisplayType.ActionsBar || visualizationType === ChartDisplayType.ActionsStackedBar

    const typedConfig = useMemo(() => {
        if (!xData) {
            return undefined
        }
        return isBar
            ? {
                  chartType: 'bar' as const,
                  config: buildBarChartConfig({ xData, chartSettings, timezone, goalLines, visualizationType }),
              }
            : {
                  chartType: 'line' as const,
                  config: buildLineChartConfig({ xData, chartSettings, timezone, goalLines }),
              }
    }, [xData, chartSettings, timezone, goalLines, visualizationType, isBar])

    if (!xData || !ySeriesData || series.length === 0 || !typedConfig) {
        return null
    }

    return { ...typedConfig, series, labels: xData.data, theme }
}
