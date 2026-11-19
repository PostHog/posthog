import posthog from 'posthog-js'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'

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
    compact = false,
}: {
    serviceName: string
    timeRange: TimeRange
    /** The surface the link sits on, for usage tracking. */
    source: string
    signals?: TelemetrySignal[]
    /** Folds the links into one menu button, for tables too narrow to show them side by side. */
    compact?: boolean
}): JSX.Element {
    if (compact) {
        return (
            <More
                aria-label="Open in"
                tooltip="Open in"
                data-attr="apm-open-in-menu"
                overlay={signals.map((signal) => (
                    <LemonButton
                        key={signal}
                        fullWidth
                        to={signalUrl(signal, serviceName, timeRange)}
                        // pinned: analytics event name and properties, renaming breaks dashboards
                        onClick={() => posthog.capture('apm telemetry link clicked', { signal, source })}
                        data-attr={`apm-open-${signal}`}
                    >
                        Open in {LABEL[signal].toLowerCase()}
                    </LemonButton>
                ))}
            />
        )
    }
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
