import clsx from 'clsx'
import { useMemo } from 'react'

import { ScatterChart } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import { ChartSettings } from '~/queries/schema/schema-general'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { AxisSeries } from '../../dataVisualizationLogic'
import { buildScatterConfig, buildScatterSeries } from './sqlScatterGraphAdapter'

const handleChartError = makeChartErrorHandler('sql-scatter-chart')

export interface SqlScatterGraphProps {
    /** The x column. Both axes are continuous, so a non-numeric column has nothing to plot. */
    xData: AxisSeries<string> | null
    yData: AxisSeries<number | null>[]
    chartSettings: ChartSettings
    presetChartHeight?: boolean
    className?: string
}

/** SQL scatter plot on @posthog/quill-charts' {@link ScatterChart} — one series per selected Y
 *  column, one marker per result row. */
export const SqlScatterGraph = ({
    xData,
    yData,
    chartSettings,
    presetChartHeight,
    className,
}: SqlScatterGraphProps): JSX.Element => {
    const theme = useChartTheme()

    const series = useMemo(() => buildScatterSeries(xData, yData), [xData, yData])
    const config = useChartConfig(
        () => (xData ? buildScatterConfig({ xData, yData, chartSettings }) : undefined),
        [xData, yData, chartSettings]
    )

    const hasPoints = series.some((s) => s.points.length > 0)

    if (!hasPoints || !config) {
        return (
            <div className={clsx(className, 'rounded bg-surface-primary flex flex-1 items-center justify-center p-6')}>
                <span className="text-secondary text-sm">
                    No points to plot. Pick a numeric column for each axis, and make sure some rows have a value in
                    both.
                </span>
            </div>
        )
    }

    return (
        <div
            className={clsx(
                className,
                'rounded bg-surface-primary w-full grow relative overflow-hidden flex flex-col',
                { 'h-[60vh]': presetChartHeight, 'h-full': !presetChartHeight }
            )}
        >
            <ScatterChart
                series={series}
                theme={theme}
                config={config}
                dataAttr="sql-scatter-chart"
                onError={handleChartError}
            />
        </div>
    )
}
