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

import { findFirstCrossing, forecastGoalLines, targetSummary } from './forecastPreviewUtils'

const handleChartError = makeChartErrorHandler('alerts-forecast-preview-chart')

function dateLabel(value: string): string {
    const parsed = dayjs(value)
    return parsed.isValid() ? parsed.format('MMM D, YYYY') : value
}

function ForecastChart({
    result,
    thresholdBounds,
    forecastConfig,
    markerIndex,
}: {
    result: ForecastSimulateResponseApi
    thresholdBounds: InsightsThresholdBounds | null
    forecastConfig: ForecastConfig
    markerIndex: number | null
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
                    fromIndex: Math.max(historyLength - 1, 0),
                    pattern: [6, 4],
                },
            },
        },
    ]
    const lower = [...result.data, ...result.forecast_lower]
    const upper = [...result.data, ...result.forecast_upper]
    const markerDataIndex = markerIndex == null ? null : historyLength + markerIndex
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
                    xAxis: { hide: true },
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
}: {
    result: ForecastSimulateResponseApi
    thresholdBounds: InsightsThresholdBounds | null
    forecastConfig: ForecastConfig
}): JSX.Element {
    const crossingIndex =
        forecastConfig.condition === ForecastConditionType.FUTURE_BREACH
            ? findFirstCrossing(result.forecast_yhat, thresholdBounds)
            : null
    const targetIndex = result.target_projection
        ? result.forecast_dates.indexOf(result.target_projection.evaluated_date)
        : null
    const markerIndex = targetIndex != null && targetIndex >= 0 ? targetIndex : crossingIndex

    return (
        <div className="space-y-2">
            <ForecastChart
                result={result}
                thresholdBounds={thresholdBounds}
                forecastConfig={forecastConfig}
                markerIndex={markerIndex}
            />
            <div className="text-sm">
                {forecastConfig.condition === ForecastConditionType.TARGET_BY_DATE && result.target_projection ? (
                    <span>
                        {targetSummary(result.target_projection, forecastConfig.target_direction)}. Projected{' '}
                        {humanFriendlyNumber(result.target_projection.predicted)} in the{' '}
                        {dateLabel(result.target_projection.evaluated_date)} bucket, against a target of{' '}
                        {forecastConfig.target_direction === ForecastTargetDirection.AT_MOST ? 'at most' : 'at least'}{' '}
                        {humanFriendlyNumber(result.target_projection.target)} on{' '}
                        {dateLabel(result.target_projection.target_date)}.
                    </span>
                ) : crossingIndex != null ? (
                    <span>Predicted to cross the threshold on {dateLabel(result.forecast_dates[crossingIndex])}.</span>
                ) : (
                    <span>No threshold breach is predicted within this forecast window.</span>
                )}
            </div>
            <div className="text-xs text-muted">
                The shaded range is an uncalibrated guide to uncertainty. This alert fires from the point forecast only.
            </div>
        </div>
    )
}
