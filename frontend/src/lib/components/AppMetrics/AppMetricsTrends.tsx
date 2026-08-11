import { useMemo } from 'react'

import { LemonBanner, SpinnerOverlay } from '@posthog/lemon-ui'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'
import { AppMetricsSeriesOverride, AppMetricsTimeSeriesChart } from './AppMetricsTimeSeriesChart'

export function AppMetricsTrends({
    appMetricsTrends,
    loading,
    error,
    metricLabels,
    seriesColors,
}: {
    appMetricsTrends: AppMetricsTimeSeriesResponse | null
    loading: boolean
    /** Message shown in place of the chart when the metrics query fails (e.g. a 403). */
    error?: string | null
    /** Optional display labels keyed by series name (e.g. `{ rows_synced: 'Rows synced' }`). */
    metricLabels?: Record<string, string>
    /** Optional colors keyed by series name, so a metric reads the same color here as in its tile. */
    seriesColors?: Record<string, string>
}): JSX.Element {
    const seriesOverrides = useMemo(() => {
        // Identical to the previous label-only behavior when `seriesColors` is unset, so callers that
        // don't pass colors (data pipelines, batch exports, event filtering, etc.) are unaffected.
        if (!metricLabels && !seriesColors) {
            return undefined
        }
        const names = new Set([...Object.keys(metricLabels ?? {}), ...Object.keys(seriesColors ?? {})])
        return Object.fromEntries(
            [...names].map((name): [string, AppMetricsSeriesOverride] => [
                name,
                {
                    ...(metricLabels && name in metricLabels ? { label: metricLabels[name] } : {}),
                    ...(seriesColors && name in seriesColors ? { color: seriesColors[name] } : {}),
                },
            ])
        )
    }, [metricLabels, seriesColors])

    return (
        <div className="relative border rounded min-h-[20rem] h-[70vh] bg-surface-primary">
            {loading ? (
                <SpinnerOverlay />
            ) : error ? (
                <div className="flex items-center justify-center h-full p-4">
                    <LemonBanner type="error">Could not load metrics: {error}</LemonBanner>
                </div>
            ) : !appMetricsTrends ? (
                <div className="flex-1 flex items-center justify-center">Missing</div>
            ) : (
                <AppMetricsTimeSeriesChart
                    className="p-2"
                    timeSeries={appMetricsTrends}
                    seriesOverrides={seriesOverrides}
                    showLegend
                />
            )}
        </div>
    )
}
