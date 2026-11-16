import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import type { EndpointHealthApi } from './generated/api.schemas'
import { healthColumns } from './healthColumns'
import { TelemetryLinks } from './TelemetryLinks'

export function EndpointsTab(): JSX.Element {
    const { endpoints, endpointsHealthLoading, endpointsLoadError, services, endpointsService, timeRange } =
        useValues(applicationObservabilityLogic)
    const { setEndpointsService } = useActions(applicationObservabilityLogic)

    const serviceNames = services.map((row) => row.service_name)
    if (endpointsService && !serviceNames.includes(endpointsService)) {
        serviceNames.push(endpointsService)
    }

    const columns: LemonTableColumns<EndpointHealthApi> = [
        {
            title: 'Endpoint',
            key: 'endpoint',
            render: (_, row) => (
                <Link
                    to={urls.tracingOperation(row.service_name, row.endpoint, { date_from: timeRange, date_to: null })}
                    className="font-semibold"
                    data-attr="apm-endpoint-operation"
                >
                    {row.endpoint}
                </Link>
            ),
        },
        {
            title: 'Service',
            key: 'service_name',
            render: (_, row) => row.service_name,
        },
        ...healthColumns<EndpointHealthApi>(),
        {
            title: 'Open in',
            key: 'links',
            render: (_, row) => (
                <span className="flex gap-2">
                    <TelemetryLinks serviceName={row.service_name} timeRange={timeRange} />
                </span>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    size="small"
                    value={endpointsService}
                    onChange={(value) => setEndpointsService(value)}
                    options={[
                        { value: null, label: 'All services' },
                        ...serviceNames.map((name) => ({ value: name, label: name })),
                    ]}
                    data-attr="apm-endpoints-service"
                />
            </div>
            {endpointsLoadError && (
                <LemonBanner type="error">
                    {endpoints.length > 0
                        ? "Couldn't refresh endpoints. Showing the last successful results."
                        : "Couldn't load endpoints. Try again shortly."}
                </LemonBanner>
            )}
            <LemonTable
                columns={columns}
                dataSource={endpoints}
                rowKey={(row) => `${row.service_name}\n${row.endpoint}`}
                loading={endpointsHealthLoading}
                emptyState="No endpoints in this environment and time range. Endpoints come from the requests, messages, and jobs your services handle."
                data-attr="apm-endpoints-table"
            />
        </div>
    )
}
