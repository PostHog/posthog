import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { TimeRange, drillDownParams } from './applicationObservabilityLogic'

export function TelemetryLinks({ serviceName, timeRange }: { serviceName: string; timeRange: TimeRange }): JSX.Element {
    return (
        <>
            <Link to={`${urls.tracing()}?${drillDownParams(serviceName, timeRange)}`}>Traces</Link>
            <Link to={`${urls.logs()}?${drillDownParams(serviceName, timeRange)}`}>Logs</Link>
        </>
    )
}
