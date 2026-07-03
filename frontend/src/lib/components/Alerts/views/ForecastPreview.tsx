import annotationPlugin from 'chartjs-plugin-annotation'

import { LemonTag } from '@posthog/lemon-ui'

import { Chart } from 'lib/Chart'
import { useChart } from 'lib/hooks/useChart'

import { InsightsThresholdBounds } from '~/queries/schema/schema-general'

import { ForecastSimulateResponseApi, VerdictEnumApi } from 'products/alerts/frontend/generated/api.schemas'

import { findFirstCrossing } from './forecastPreviewUtils'
import { formatSimDate } from './SimulationSummary'

Chart.register(annotationPlugin)

const FIT_QUALITY_COPY: Record<VerdictEnumApi, { type: 'success' | 'warning' | 'danger'; label: string } | null> = {
    [VerdictEnumApi.Good]: { type: 'success', label: 'Good fit' },
    [VerdictEnumApi.Noisy]: { type: 'warning', label: 'Noisy fit — alerts may be sensitive' },
    [VerdictEnumApi.Poor]: { type: 'danger', label: 'Poor fit — the forecast may not be reliable' },
    // Not enough data to assess the fit — hide the badge rather than guess.
    [VerdictEnumApi.Unknown]: null,
}

function formatPercent(value: number | null): string | null {
    return value == null ? null : `${Math.round(value * 100)}%`
}

/** For band-deviation mode there's no threshold to cross — fall back to the nearest forecast band
 * (the first predicted interval) as a proxy for "the expected range right now". */
function isLatestValueOutsideNearBand(result: ForecastSimulateResponseApi): boolean | null {
    const latest = result.data[result.data.length - 1]
    const lower = result.forecast_lower[0]
    const upper = result.forecast_upper[0]
    if (latest == null || lower == null || upper == null) {
        return null
    }
    return latest < lower || latest > upper
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
    const mape = formatPercent(fitQuality.mape)
    const coverage = formatPercent(fitQuality.coverage)
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
    const upperData = nullPad(result.forecast_upper)
    const lowerData = nullPad(result.forecast_lower)

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
    const outsideNearBand = !hasBounds ? isLatestValueOutsideNearBand(result) : null

    return (
        <div className="rounded-lg p-3 space-y-2">
            <FitQualityBadge fitQuality={result.fit_quality} />
            <ForecastChart
                result={result}
                thresholdBounds={hasBounds ? thresholdBounds : null}
                crossingIndex={crossingIndex}
            />
            <div className="text-sm text-muted">
                {hasBounds ? (
                    crossingIndex != null ? (
                        <span>
                            Predicted to cross the threshold on {formatSimDate(result.forecast_dates[crossingIndex])}
                        </span>
                    ) : (
                        <span>No breach predicted within the forecast window</span>
                    )
                ) : outsideNearBand == null ? (
                    <span>Not enough data to assess the expected range</span>
                ) : (
                    <span>Latest value is {outsideNearBand ? 'outside' : 'near'} its forecasted range</span>
                )}
            </div>
        </div>
    )
}
