import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSelect, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import { endpointOperationUrl } from './endpointOperationUrl'
import { EndpointTimeSpent } from './EndpointTimeSpent'
import type { EndpointHealthApi } from './generated/api.schemas'
import { healthColumns } from './healthColumns'
import { HealthTableLink } from './HealthTableLink'
import { TelemetryLinks } from './TelemetryLinks'

export function EndpointsTab(): JSX.Element {
    const {
        endpoints,
        filteredEndpoints,
        search,
        endpointsHealthLoading,
        endpointsLoadError,
        services,
        endpointsService,
        timeRange,
    } = useValues(applicationObservabilityLogic)
    const { setEndpointsService, setSearch } = useActions(applicationObservabilityLogic)

    const serviceNames = services.map((row) => row.service_name)
    if (endpointsService && !serviceNames.includes(endpointsService)) {
        serviceNames.push(endpointsService)
    }

    const columns: LemonTableColumns<EndpointHealthApi> = [
        {
            title: 'Endpoint',
            key: 'endpoint',
            sorter: (a, b) => a.endpoint.localeCompare(b.endpoint),
            render: (_, row) => (
                <HealthTableLink
                    to={endpointOperationUrl(row, { date_from: timeRange, date_to: null })}
                    data-attr="apm-endpoint-operation"
                >
                    {row.endpoint}
                </HealthTableLink>
            ),
        },
        {
            title: 'Service',
            key: 'service_name',
            sorter: (a, b) => a.service_name.localeCompare(b.service_name),
            render: (_, row) => row.service_name,
        },
        ...healthColumns<EndpointHealthApi>(filteredEndpoints),
        {
            title: 'Open in',
            key: 'links',
            render: (_, row) => (
                <span className="flex gap-2">
                    <TelemetryLinks serviceName={row.service_name} timeRange={timeRange} source="endpoints" />
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
                <LemonInput
                    type="search"
                    size="small"
                    className="max-w-80"
                    placeholder="Search endpoints"
                    value={search}
                    onChange={setSearch}
                    data-attr="apm-endpoints-search"
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
                dataSource={filteredEndpoints}
                rowKey={(row) => `${row.service_name}\n${row.endpoint}`}
                loading={endpointsHealthLoading}
                emptyState={
                    endpoints.length > 0
                        ? `No endpoints match "${search}".`
                        : 'No endpoints in this environment and time range. Endpoints come from the requests, messages, and jobs your services handle.'
                }
                expandable={{
                    noIndent: true,
                    expandedRowRender: (row) => (
                        <EndpointTimeSpent
                            service={row.service_name}
                            endpoint={row.endpoint}
                            environment={row.environment}
                        />
                    ),
                }}
                data-attr="apm-endpoints-table"
            />
        </div>
    )
}
