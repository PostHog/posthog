import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import type { LemonMenuSection } from 'lib/lemon-ui/LemonMenu'
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

/** The "Open in" links as a menu section, for tables too narrow to show them side by side. */
export function telemetryMenuSection(
    serviceName: string,
    timeRange: TimeRange,
    source: string,
    signals: TelemetrySignal[] = ALL_SIGNALS
): LemonMenuSection {
    return {
        title: 'Open in',
        items: signals.map((signal) => ({
            label: LABEL[signal],
            to: signalUrl(signal, serviceName, timeRange),
            // pinned: analytics event name and properties, renaming breaks dashboards
            onClick: () => posthog.capture('apm telemetry link clicked', { signal, source }),
            'data-attr': `apm-open-${signal}`,
        })),
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
