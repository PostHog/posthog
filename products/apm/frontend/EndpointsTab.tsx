import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonSelect, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import type { TracesAlertFormType } from 'products/tracing/frontend/alerting/tracesAlertUtils'

import { AlertOnThisMenu } from './AlertOnThisMenu'
import { endpointAlertTarget } from './alertPresets'
import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import { endpointOperationUrl } from './endpointOperationUrl'
import { EndpointTimeSpent } from './EndpointTimeSpent'
import type { EndpointHealthApi } from './generated/api.schemas'
import { healthColumns } from './healthColumns'
import { HealthTableLink } from './HealthTableLink'
import { telemetryMenuSection } from './TelemetryLinks'

export interface EndpointsTabProps {
    /** Absent when traces alerts are off, which leaves only the "Open in" links in the row menu. */
    onCreateAlert?: (form: TracesAlertFormType) => void
}

export function EndpointsTab({ onCreateAlert }: EndpointsTabProps): JSX.Element {
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
                    className="block max-w-36 truncate"
                    title={row.endpoint}
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
            render: (_, row) => (
                <span className="block max-w-28 truncate" title={row.service_name}>
                    {row.service_name}
                </span>
            ),
        },
        ...healthColumns<EndpointHealthApi>(filteredEndpoints),
        {
            key: 'actions',
            width: 0,
            render: (_, row) => (
                <AlertOnThisMenu
                    target={endpointAlertTarget(row)}
                    source="endpoints"
                    onCreateAlert={onCreateAlert}
                    leadingSections={[telemetryMenuSection(row.service_name, timeRange, 'endpoints')]}
                />
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
