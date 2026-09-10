import {
    AnomalyPointsLayer,
    DEFAULT_Y_AXIS_ID,
    type Series,
    TimeSeriesLineChart,
    useChartTheme,
} from '@posthog/quill-charts'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    ForecastConditionType,
    ForecastConfig,
    ForecastTargetDirection,
    InsightsThresholdBounds,
} from '~/queries/schema/schema-general'

import { ForecastSimulateResponseApi } from 'products/alerts/frontend/generated/api.schemas'
import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import {
    bucketLabel,
    chartInterval,
    findFirstCrossing,
    findObservedBreach,
    forecastGoalLines,
    targetSummary,
} from './forecastPreviewUtils'

const handleChartError = makeChartErrorHandler('alerts-forecast-preview-chart')

/** For the target date the user picked, which is a calendar day rather than a bucket. Bucket
 *  timestamps go through `bucketLabel`, which keeps the hour on an hourly insight. */
function dateLabel(value: string): string {
    const parsed = dayjs(value)
    return parsed.isValid() ? parsed.format('MMM D, YYYY') : value
}

function ForecastChart({
    result,
    thresholdBounds,
    forecastConfig,
    projectTimezone,
    markerDataIndex,
}: {
    result: ForecastSimulateResponseApi
    thresholdBounds: InsightsThresholdBounds | null
    forecastConfig: ForecastConfig
    projectTimezone: string
    markerDataIndex: number | null
}): JSX.Element {
    const theme = useChartTheme()
    const historyLength = result.data.length
    const values = [...result.data, ...result.forecast_yhat]
    const labels = [...result.dates, ...result.forecast_dates]
    const series: Series[] = [
        {
            key: 'forecast',
            label: 'Value',
            data: values,
            color: 'rgba(99, 102, 241, 0.9)',
            stroke: {
                partial: {
                    // The renderer shares the boundary point, so it starts the dashed run one index
                    // before `fromIndex`. The first forecast index therefore keeps every measured
                    // segment solid and dashes the segment that bridges history and forecast.
                    fromIndex: historyLength,
                    pattern: [6, 4],
                },
            },
        },
    ]
    const lower = [...result.data, ...result.forecast_lower]
    const upper = [...result.data, ...result.forecast_upper]
    const markerValue = markerDataIndex == null ? null : values[markerDataIndex]
    const markerColor =
        forecastConfig.condition === ForecastConditionType.TARGET_BY_DATE && !result.target_projection?.misses_target
            ? 'rgba(22, 163, 74, 0.9)'
            : 'rgba(220, 38, 38, 0.9)'

    return (
        <div className="h-40 flex flex-col" data-attr="forecast-preview-chart">
            <TimeSeriesLineChart
                series={series}
                labels={labels}
                theme={theme}
                config={{
                    // The axis is hidden, so the timezone is here for the tooltip: the chart formats
                    // the header date only when it knows the zone to read each label in. Without it
                    // the tooltip prints the raw API timestamp, and it is the only date this chart
                    // shows. The engine sends history as project-local wall time and hourly forecast
                    // buckets with the project offset attached, and the chart reads both against this
                    // zone, so the header names the bucket the backend evaluated.
                    xAxis: { hide: true, timezone: projectTimezone, interval: chartInterval(result.interval) },
                    yAxis: {
                        showGrid: true,
                        startAtZero: false,
                        tickFormatter: (value) => humanFriendlyNumber(value),
                    },
                    goalLines: forecastGoalLines(thresholdBounds, forecastConfig),
                    confidenceIntervals: [{ seriesKey: 'forecast', lower, upper }],
                    tooltip: { valueFormatter: (value) => humanFriendlyNumber(value) },
                }}
                onError={handleChartError}
            >
                {markerDataIndex != null && markerValue != null ? (
                    <AnomalyPointsLayer
                        markers={[
                            {
                                dataIndex: markerDataIndex,
                                value: markerValue,
                                color: markerColor,
                                yAxisId: DEFAULT_Y_AXIS_ID,
                            },
                        ]}
                    />
                ) : null}
            </TimeSeriesLineChart>
        </div>
    )
}

export function ForecastPreview({
    result,
    thresholdBounds,
    forecastConfig,
    projectTimezone,
}: {
    result: ForecastSimulateResponseApi
    thresholdBounds: InsightsThresholdBounds | null
    forecastConfig: ForecastConfig
    projectTimezone: string
}): JSX.Element {
    const isFutureBreach = forecastConfig.condition === ForecastConditionType.FUTURE_BREACH
    const observedBreach = isFutureBreach ? findObservedBreach(result.data, thresholdBounds) : null
    const crossingIndex =
        isFutureBreach && !observedBreach ? findFirstCrossing(result.forecast_yhat, thresholdBounds) : null
    const targetIndex = result.target_projection
        ? result.forecast_dates.indexOf(result.target_projection.evaluated_date)
        : null
    const forecastMarkerIndex = targetIndex != null && targetIndex >= 0 ? targetIndex : crossingIndex
    const markerDataIndex = observedBreach
        ? observedBreach.index
        : forecastMarkerIndex == null
          ? null
          : result.data.length + forecastMarkerIndex

    return (
        <div className="space-y-2">
            <ForecastChart
                result={result}
                thresholdBounds={thresholdBounds}
                forecastConfig={forecastConfig}
                projectTimezone={projectTimezone}
                markerDataIndex={markerDataIndex}
            />
            <div className="text-sm">
                {forecastConfig.condition === ForecastConditionType.TARGET_BY_DATE && result.target_projection ? (
                    <span>
                        {targetSummary(result.target_projection, forecastConfig.target_direction)}. Projected{' '}
                        {humanFriendlyNumber(result.target_projection.predicted)} in the{' '}
                        {bucketLabel(result.target_projection.evaluated_date, result.interval)} bucket, against a target
                        of{' '}
                        {forecastConfig.target_direction === ForecastTargetDirection.AT_MOST ? 'at most' : 'at least'}{' '}
                        {humanFriendlyNumber(result.target_projection.target)} on{' '}
                        {dateLabel(result.target_projection.target_date)}.
                    </span>
                ) : observedBreach ? (
                    <span>
                        The latest value on {bucketLabel(result.dates[observedBreach.index], result.interval)} (
                        {humanFriendlyNumber(observedBreach.value)}) already crosses the threshold, so this alert fires
                        on the next check.
                    </span>
                ) : crossingIndex != null ? (
                    <span>
                        Predicted to cross the threshold on{' '}
                        {bucketLabel(result.forecast_dates[crossingIndex], result.interval)}.
                    </span>
                ) : (
                    <span>No threshold breach is predicted within this forecast window.</span>
                )}
            </div>
            <div className="text-xs text-muted">
                The shaded range is an uncalibrated guide to uncertainty.{' '}
                {isFutureBreach
                    ? 'This alert fires from the point forecast, or from the latest value if it already crosses the threshold.'
                    : 'This alert fires from the point forecast only.'}
            </div>
        </div>
    )
}
