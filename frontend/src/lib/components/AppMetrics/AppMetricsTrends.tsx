import { useMemo } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'
import { AppMetricsSeriesOverride, AppMetricsTimeSeriesChart } from './AppMetricsTimeSeriesChart'

export function AppMetricsTrends({
    appMetricsTrends,
    loading,
    metricLabels,
}: {
    appMetricsTrends: AppMetricsTimeSeriesResponse | null
    loading: boolean
    /** Optional display labels keyed by series name (e.g. `{ rows_synced: 'Rows synced' }`). */
    metricLabels?: Record<string, string>
}): JSX.Element {
    const seriesOverrides = useMemo(
        () =>
            metricLabels
                ? Object.fromEntries(
                      Object.entries(metricLabels).map(([name, label]): [string, AppMetricsSeriesOverride] => [
                          name,
                          { label },
                      ])
                  )
                : undefined,
        [metricLabels]
    )

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
