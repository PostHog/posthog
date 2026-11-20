import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { TimeRange, drillDownParams, metricsDrillDownUrl } from './applicationObservabilityLogic'

export type TelemetrySignal = 'traces' | 'logs' | 'metrics'

const ALL_SIGNALS: TelemetrySignal[] = ['traces', 'logs', 'metrics']

const LABEL: Record<TelemetrySignal, string> = { traces: 'Traces', logs: 'Logs', metrics: 'Metrics' }

function signalUrl(signal: TelemetrySignal, serviceName: string, timeRange: TimeRange): string {
    switch (signal) {
        case 'traces':
            return `${urls.tracing()}?${drillDownParams(serviceName, timeRange)}`
        case 'logs':
            return `${urls.logs()}?${drillDownParams(serviceName, timeRange)}`
        case 'metrics':
            return metricsDrillDownUrl(serviceName, timeRange)
    }
}

export function TelemetryLinks({
    serviceName,
    timeRange,
    source,
    signals = ALL_SIGNALS,
}: {
    serviceName: string
    timeRange: TimeRange
    /** The surface the link sits on, for usage tracking. */
    source: string
    signals?: TelemetrySignal[]
}): JSX.Element {
    return (
        <>
            {signals.map((signal) => (
                <Link
                    key={signal}
                    to={signalUrl(signal, serviceName, timeRange)}
                    // pinned: analytics event name and properties, renaming breaks dashboards
                    onClick={() => posthog.capture('apm telemetry link clicked', { signal, source })}
                    data-attr={`apm-open-${signal}`}
                >
                    {LABEL[signal]}
                </Link>
            ))}
        </>
    )
}
