import annotationPlugin from 'chartjs-plugin-annotation'

import { LemonTag } from '@posthog/lemon-ui'

import { Chart } from 'lib/Chart'
import { dayjs } from 'lib/dayjs'
import { useChart } from 'lib/hooks/useChart'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import {
    ForecastConditionType,
    ForecastConfig,
    ForecastSensitivity,
    InsightsThresholdBounds,
} from '~/queries/schema/schema-general'

import {
    ForecastSimulateResponseApi,
    ForecastFitQualityVerdictEnumApi,
} from 'products/alerts/frontend/generated/api.schemas'

import { findFirstCrossing, targetSummary } from './forecastPreviewUtils'
import { formatSimDate } from './SimulationSummary'

Chart.register(annotationPlugin)

const FIT_QUALITY_COPY: Record<
    ForecastFitQualityVerdictEnumApi,
    { type: 'success' | 'warning' | 'danger'; label: string } | null
> = {
    [ForecastFitQualityVerdictEnumApi.Good]: { type: 'success', label: 'Good fit' },
    [ForecastFitQualityVerdictEnumApi.Noisy]: { type: 'warning', label: 'Noisy fit - this alert may fire often' },
    [ForecastFitQualityVerdictEnumApi.Poor]: { type: 'danger', label: 'Poor fit - the forecast may not be reliable' },
    [ForecastFitQualityVerdictEnumApi.Unknown]: null,
}

function FitQualityBadge({
    fitQuality,
}: {
    fitQuality: ForecastSimulateResponseApi['fit_quality']
}): JSX.Element | null {
    const copy = FIT_QUALITY_COPY[fitQuality.verdict]
    if (!copy) {
        return null
    }
    const mape = fitQuality.mape == null ? null : percentage(fitQuality.mape, 0)
    const coverage = fitQuality.coverage == null ? null : percentage(fitQuality.coverage, 0)
    return (
        <div className="flex flex-wrap items-center gap-2">
            <LemonTag type={copy.type}>{copy.label}</LemonTag>
            {mape != null && coverage != null && (
                <span className="text-xs text-muted">
                    Forecast is on average {mape} off; {coverage} of history falls inside the expected range
                </span>
            )}
        </div>
    )
}

function ForecastChart({
    result,
    thresholdBounds,
    crossingIndex,
}: {
    result: ForecastSimulateResponseApi
    thresholdBounds: InsightsThresholdBounds | null
    crossingIndex: number | null
}): JSX.Element {
    const historyLength = result.dates.length
    const forecastLength = result.forecast_dates.length
    const lastActual = result.data[result.data.length - 1] ?? null

    const nullPad = (values: number[]): (number | null)[] => [
        ...Array(Math.max(historyLength - 1, 0)).fill(null),
        lastActual,
        ...values,
    ]

    const forecastData = nullPad(result.forecast_yhat)

    const { history_lower: historyLower, history_upper: historyUpper } = result
    const hasHistoryBand =
        historyLower != null &&
        historyUpper != null &&
        historyLower.length === historyLength &&
        historyUpper.length === historyLength
    const upperData = hasHistoryBand ? [...historyUpper, ...result.forecast_upper] : nullPad(result.forecast_upper)
    const lowerData = hasHistoryBand ? [...historyLower, ...result.forecast_lower] : nullPad(result.forecast_lower)

    const crossingDataIndex = crossingIndex != null ? historyLength + crossingIndex : null
    const pointRadius = forecastData.map((_, i) => (i === crossingDataIndex ? 4 : 0))
    const pointBackgroundColor = forecastData.map((_, i) =>
        i === crossingDataIndex ? 'rgba(220, 38, 38, 0.9)' : 'transparent'
    )
    const pointBorderColor = forecastData.map((_, i) =>
        i === crossingDataIndex ? 'rgba(153, 27, 27, 1)' : 'transparent'
    )

    const { canvasRef } = useChart({
        getConfig: () => ({
            type: 'line' as const,
            data: {
                labels: [...result.dates, ...result.forecast_dates],
                datasets: [
                    {
                        label: 'History',
                        data: [...result.data, ...Array(forecastLength).fill(null)],
                        borderColor: 'rgba(99, 102, 241, 0.8)',
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                    },
                    {
                        label: 'Forecast',
                        data: forecastData,
                        borderColor: 'rgba(99, 102, 241, 0.8)',
                        borderDash: [6, 4],
                        borderWidth: 1.5,
                        pointRadius,
                        pointBackgroundColor,
                        pointBorderColor,
                        pointBorderWidth: forecastData.map((_, i) => (i === crossingDataIndex ? 1 : 0)),
                        fill: false,
                    },
                    {
                        label: 'Upper',
                        data: upperData,
                        borderColor: 'transparent',
                        pointRadius: 0,
                        fill: '+1',
                        backgroundColor: 'rgba(99, 102, 241, 0.12)',
                    },
                    {
                        label: 'Lower',
                        data: lowerData,
                        borderColor: 'transparent',
                        pointRadius: 0,
                        fill: false,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { enabled: true },
                    annotation:
                        thresholdBounds && (thresholdBounds.upper != null || thresholdBounds.lower != null)
                            ? {
                                  annotations: {
                                      ...(thresholdBounds.upper != null
                                          ? {
                                                upperBound: {
                                                    type: 'line' as const,
                                                    yMin: thresholdBounds.upper,
                                                    yMax: thresholdBounds.upper,
                                                    borderColor: 'rgba(220, 38, 38, 0.6)',
                                                    borderWidth: 1.5,
                                                    borderDash: [4, 4],
                                                },
                                            }
                                          : {}),
                                      ...(thresholdBounds.lower != null
                                          ? {
                                                lowerBound: {
                                                    type: 'line' as const,
                                                    yMin: thresholdBounds.lower,
                                                    yMax: thresholdBounds.lower,
                                                    borderColor: 'rgba(220, 38, 38, 0.6)',
                                                    borderWidth: 1.5,
                                                    borderDash: [4, 4],
                                                },
                                            }
                                          : {}),
                                  },
                              }
                            : undefined,
                },
                scales: {
                    x: { display: false },
                    y: { display: true, ticks: { maxTicksLimit: 3, font: { size: 10 } }, grid: { drawTicks: false } },
                },
                elements: { line: { tension: 0 } },
            },
        }),
        deps: [result, thresholdBounds, crossingIndex],
    })

    return (
        <div className="h-32">
            <canvas ref={canvasRef} />
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
    forecastConfig: ForecastConfig | null
}): JSX.Element {
    const hasBounds = !!thresholdBounds && (thresholdBounds.upper != null || thresholdBounds.lower != null)
    const bestCase = forecastConfig?.sensitivity === ForecastSensitivity.BEST_CASE
    const crossingIndex = hasBounds
        ? findFirstCrossing(
              { yhat: result.forecast_yhat, lower: result.forecast_lower, upper: result.forecast_upper },
              thresholdBounds,
              bestCase
          )
        : null
    const deviation = result.latest_deviation
    const projection = result.target_projection

    return (
        <div className="space-y-2">
            <FitQualityBadge fitQuality={result.fit_quality} />
            <ForecastChart
                result={result}
                thresholdBounds={hasBounds ? thresholdBounds : null}
                crossingIndex={crossingIndex}
            />
            <div className="text-sm text-muted">
                {projection ? (
                    <span>
                        {targetSummary(projection, forecastConfig?.target_direction)}. Projected{' '}
                        {humanFriendlyNumber(projection.predicted)} on{' '}
                        {dayjs(projection.target_date).format('MMM D, YYYY')} against a target of{' '}
                        {humanFriendlyNumber(projection.target)}.
                    </span>
                ) : hasBounds ? (
                    crossingIndex != null ? (
                        <span>
                            Predicted to cross the threshold on {formatSimDate(result.forecast_dates[crossingIndex])}
                        </span>
                    ) : (
                        <span>Not predicted to cross the threshold within the forecast window</span>
                    )
                ) : forecastConfig?.condition === ForecastConditionType.FUTURE_BREACH ? (
                    <span>Set less than or more than to see when this is predicted to breach</span>
                ) : deviation == null ? (
                    <span>
                        {forecastConfig?.condition === ForecastConditionType.TARGET_BY_DATE
                            ? 'Set a target and a date to see whether this metric is on track'
                            : 'Not enough history yet. Pick a longer date range on the insight.'}
                    </span>
                ) : (
                    <span>
                        Latest value {humanFriendlyNumber(deviation.value)} is{' '}
                        {deviation.outside ? 'outside' : 'inside'} its expected range of{' '}
                        {humanFriendlyNumber(deviation.lower)} to {humanFriendlyNumber(deviation.upper)}
                    </span>
                )}
            </div>
        </div>
    )
}
