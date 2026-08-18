import annotationPlugin from 'chartjs-plugin-annotation'

import { LemonTag } from '@posthog/lemon-ui'

import { Chart } from 'lib/Chart'
import { useChart } from 'lib/hooks/useChart'
import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import { InsightsThresholdBounds } from '~/queries/schema/schema-general'

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
    [ForecastFitQualityVerdictEnumApi.Noisy]: { type: 'warning', label: 'Noisy fit, alerts may be sensitive' },
    [ForecastFitQualityVerdictEnumApi.Poor]: { type: 'danger', label: 'Poor fit, the forecast may not be reliable' },
    // Not enough data to assess the fit, so hide the badge rather than guess.
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
                    Forecast is on average {mape} off; {coverage} of history fell inside the expected range
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

    // Anchor the forecast line to the last actual point so History and Forecast connect visually.
    const nullPad = (values: number[]): (number | null)[] => [
        ...Array(Math.max(historyLength - 1, 0)).fill(null),
        lastActual,
        ...values,
    ]

    const forecastData = nullPad(result.forecast_yhat)

    // The in-sample band comes from the same fit as the forecast band, so the two join into one
    // continuous interval. Engines that produce no in-sample band fall back to the forecast span.
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
}: {
    result: ForecastSimulateResponseApi
    thresholdBounds: InsightsThresholdBounds | null
}): JSX.Element {
    const hasBounds = !!thresholdBounds && (thresholdBounds.upper != null || thresholdBounds.lower != null)
    const crossingIndex = hasBounds ? findFirstCrossing(result.forecast_yhat, thresholdBounds) : null
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
                        {targetSummary(projection)}. Projected {humanFriendlyNumber(projection.predicted)} on{' '}
                        {formatSimDate(projection.target_date)} against a target of{' '}
                        {humanFriendlyNumber(projection.target)}.
                    </span>
                ) : hasBounds ? (
                    crossingIndex != null ? (
                        <span>
                            Predicted to cross the threshold on {formatSimDate(result.forecast_dates[crossingIndex])}
                        </span>
                    ) : (
                        <span>No breach predicted within the forecast window</span>
                    )
                ) : deviation == null ? (
                    <span>Not enough data to assess the expected range</span>
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
