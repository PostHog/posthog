import { useValues } from 'kea'
import { useMemo } from 'react'

import { TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { teamLogic } from 'scenes/teamLogic'

import type { ProcessedChartData } from '../../experimentTimeseriesLogic'
import { useChartColors } from '../shared/colors'
import { VariantTimeseriesTooltip } from './VariantTimeseriesTooltip'
import { DELTA_SERIES_KEY, buildVariantTimeseriesSeries } from './variantTimeseriesTransforms'

export interface VariantTimeseriesChartProps {
    chartData: ProcessedChartData
    isRatioMetric?: boolean
}

export function VariantTimeseriesChart({
    chartData: data,
    isRatioMetric = false,
}: VariantTimeseriesChartProps): JSX.Element {
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const colors = useChartColors()

    const { labels, processedData, computedAt, variantColor } = data

    const { series, lowerBounds, upperBounds } = useMemo(
        () => buildVariantTimeseriesSeries(processedData, variantColor),
        [processedData, variantColor]
    )

    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { interval: 'day', timezone },
            yAxis: { format: 'percentage_scaled', decimalPlaces: 0 },
            confidenceIntervals: [{ seriesKey: DELTA_SERIES_KEY, lower: lowerBounds, upper: upperBounds }],
            // A goal line rather than an overlay child: it also stretches the axis so zero stays
            // on-plot when every delta sits on one side of it.
            goalLines: [{ value: 0, displayLabel: false, color: colors.ZERO_LINE }],
        }),
        [timezone, lowerBounds, upperBounds, colors.ZERO_LINE]
    )

    return (
        <div className="relative h-[224px] flex flex-col">
            <TimeSeriesLineChart
                series={series}
                labels={labels}
                theme={theme}
                config={config}
                tooltip={({ dataIndex }) => {
                    const point = processedData[dataIndex]
                    if (!point) {
                        return null
                    }
                    return (
                        <VariantTimeseriesTooltip
                            date={point.date}
                            delta={point.value}
                            lowerBound={point.lower_bound}
                            upperBound={point.upper_bound}
                            isRatioMetric={isRatioMetric}
                            exposures={point.number_of_samples}
                            denominator={point.denominator_sum}
                            significant={point.significant}
                            hasRealData={point.hasRealData}
                            computedAt={computedAt}
                            color={variantColor}
                        />
                    )
                }}
            />
        </div>
    )
}
