import { useActions, useValues } from 'kea'

import { LemonButton, Link } from '@posthog/lemon-ui'

import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import type { ServiceEdgeApi } from './generated/api.schemas'
import { formatMs, formatPercent, formatRate } from './healthDisplay'
import { HealthStatusTag } from './HealthStatusTag'
import { TelemetryLinks } from './TelemetryLinks'

function CallList({
    title,
    edges,
    peer,
}: {
    title: string
    edges: ServiceEdgeApi[]
    peer: 'caller' | 'callee'
}): JSX.Element | null {
    if (edges.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-secondary">{title}</span>
            {edges.map((edge) => (
                <div key={`${edge.caller}->${edge.callee}`} className="flex justify-between gap-2 text-xs">
                    <span className="truncate">{edge[peer]}</span>
                    <span className="font-mono text-secondary whitespace-nowrap">
                        {edge.calls} calls · {formatPercent(edge.calls ? edge.error_count / edge.calls : 0)}
                    </span>
                </div>
            ))}
        </div>
    )
}

export function ServiceMapDetails(): JSX.Element | null {
    const { selectedMapServiceName, selectedMapService, serviceMap, timeRange } =
        useValues(applicationObservabilityLogic)
    const { setSelectedMapService, showServiceEndpoints } = useActions(applicationObservabilityLogic)

    if (!selectedMapServiceName) {
        return null
    }
    const edges = serviceMap?.edges ?? []
    const health = selectedMapService?.health

    return (
        <div
            className="flex max-h-[520px] w-72 flex-col gap-3 overflow-y-auto rounded border bg-surface-primary p-3 shadow"
            data-attr="apm-map-details"
        >
            <div className="flex items-center justify-between gap-2">
                <span className="truncate font-semibold">{selectedMapServiceName}</span>
                <LemonButton size="xsmall" onClick={() => setSelectedMapService(null)}>
                    Close
                </LemonButton>
            </div>
            {selectedMapService && health ? (
                <div className="grid grid-cols-2 gap-1 text-xs">
                    <span className="text-secondary">Health</span>
                    <span>
                        <HealthStatusTag status={selectedMapService.status} />
                    </span>
                    <span className="text-secondary">Requests</span>
                    <span className="font-mono">{formatRate(health.request_rate)}</span>
                    <span className="text-secondary">Errors</span>
                    <span className="font-mono">{formatPercent(health.error_rate)}</span>
                    <span className="text-secondary">p95</span>
                    <span className="font-mono">{formatMs(health.p95_ms)}</span>
                </div>
            ) : (
                <span className="text-xs text-secondary">
                    No health data for this service in this environment and time range.
                </span>
            )}
            <CallList
                title="Called by"
                edges={edges.filter((edge) => edge.callee === selectedMapServiceName)}
                peer="caller"
            />
            <CallList
                title="Calls"
                edges={edges.filter((edge) => edge.caller === selectedMapServiceName)}
                peer="callee"
            />
            <div className="flex gap-2 text-xs">
                <Link onClick={() => showServiceEndpoints(selectedMapServiceName)} data-attr="apm-map-endpoints">
                    Endpoints
                </Link>
                <TelemetryLinks serviceName={selectedMapServiceName} timeRange={timeRange} />
            </div>
        </div>
    )
}
