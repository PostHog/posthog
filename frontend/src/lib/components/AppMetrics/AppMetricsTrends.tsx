import { useMemo } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'
import { AppMetricsSeriesOverride, AppMetricsTimeSeriesChart } from './AppMetricsTimeSeriesChart'

export function AppMetricsTrends({
    appMetricsTrends,
    loading,
    metricLabels,
    seriesColors,
}: {
    appMetricsTrends: AppMetricsTimeSeriesResponse | null
    loading: boolean
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
