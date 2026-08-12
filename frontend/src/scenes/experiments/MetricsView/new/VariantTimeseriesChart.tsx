import { useValues } from 'kea'
import { useMemo } from 'react'

import { TimeSeriesLineChart, type Series, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { findLastIndex } from 'lib/utils/arrays'
import { teamLogic } from 'scenes/teamLogic'

import type { ProcessedChartData } from '../../experimentTimeseriesLogic'
import { useChartColors } from '../shared/colors'
import { VariantTimeseriesTooltip } from './VariantTimeseriesTooltip'

const DELTA_SERIES_KEY = 'delta'
const PENDING_DASH_PATTERN = [5, 5]

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

    const { series, lowerBounds, upperBounds } = useMemo(() => {
        // Days the daily job hasn't computed yet carry the last known value forward, so the line
        // stays continuous — dash the tail to show it isn't measured data. `fromIndex` dashes the
        // segment arriving at that point, so the first dashed segment leaves the last measured day.
        const lastRealIndex = findLastIndex(processedData, (point) => point.hasRealData)
        const firstPendingIndex = lastRealIndex + 1
        const hasPendingTail = lastRealIndex >= 0 && firstPendingIndex < processedData.length

        return {
            series: [
                {
                    key: DELTA_SERIES_KEY,
                    label: 'Delta',
                    data: processedData.map((point) => point.value ?? 0),
                    color: variantColor,
                    points: { radius: 3 },
                    stroke: hasPendingTail
                        ? { partial: { fromIndex: firstPendingIndex, pattern: PENDING_DASH_PATTERN } }
                        : undefined,
                },
            ] satisfies Series[],
            lowerBounds: processedData.map((point) => point.lower_bound ?? 0),
            upperBounds: processedData.map((point) => point.upper_bound ?? 0),
        }
    }, [processedData, variantColor])

    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { interval: 'day', timezone, tickLabelRotation: -45 },
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
                        />
                    )
                }}
            />
        </div>
    )
}
