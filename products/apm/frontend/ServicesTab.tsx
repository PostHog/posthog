import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { TracesAlertFormType } from 'products/tracing/frontend/alerting/tracesAlertUtils'

import { AlertOnThisMenu } from './AlertOnThisMenu'
import { serviceAlertTarget } from './alertPresets'
import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import { environmentLabel } from './environmentDisplay'
import type { ServiceHealthApi } from './generated/api.schemas'
import { healthColumns } from './healthColumns'
import { HealthTableLink } from './HealthTableLink'
import { Sparkline } from './Sparkline'
import { TelemetryLinks } from './TelemetryLinks'

export interface ServicesTabProps {
    /** Absent when traces alerts are off, which hides the row menu. */
    onCreateAlert?: (form: TracesAlertFormType) => void
}

export function ServicesTab({ onCreateAlert }: ServicesTabProps): JSX.Element {
    const {
        services,
        filteredServices,
        search,
        servicesHealthLoading,
        hasLoadError,
        environment,
        timeRange,
        attentionCount,
    } = useValues(applicationObservabilityLogic)
    const { showServiceEndpoints, setSearch } = useActions(applicationObservabilityLogic)

    const columns: LemonTableColumns<ServiceHealthApi> = [
        {
            title: 'Service',
            key: 'service_name',
            sorter: (a, b) => a.service_name.localeCompare(b.service_name),
            render: (_, row) => (
                <HealthTableLink
                    to={urls.applicationObservabilityService(row.service_name, { range: timeRange, environment })}
                    data-attr="apm-service-page"
                >
                    {row.service_name}
                </HealthTableLink>
            ),
        },
        ...healthColumns<ServiceHealthApi>(filteredServices),
        {
            title: 'Trend',
            key: 'sparkline',
            render: (_, row) => <Sparkline values={row.sparkline} />,
        },
        {
            title: 'Open in',
            key: 'links',
            render: (_, row) => (
                <span className="flex gap-2">
                    <Link onClick={() => showServiceEndpoints(row.service_name)} data-attr="apm-service-endpoints">
                        Endpoints
                    </Link>
                    <TelemetryLinks serviceName={row.service_name} timeRange={timeRange} source="services" />
                </span>
            ),
        },
        ...(onCreateAlert
            ? [
                  {
                      key: 'actions',
                      width: 0,
                      render: (_: unknown, row: ServiceHealthApi) => (
                          <AlertOnThisMenu
                              target={serviceAlertTarget(row)}
                              source="services"
                              onCreateAlert={onCreateAlert}
                          />
                      ),
                  },
              ]
            : []),
    ]

    const inEnvironment = environment === null ? 'across all environments' : `in ${environmentLabel(environment)}`
    const attentionMessage =
        attentionCount > 0
            ? `${attentionCount} ${attentionCount === 1 ? 'service needs' : 'services need'} attention ${inEnvironment}`
            : `All quiet ${inEnvironment}`

    return (
        <div className="flex flex-col gap-2">
            {hasLoadError ? (
                <LemonBanner type="error">
                    {services.length > 0
                        ? `Couldn't refresh service health ${inEnvironment}. Showing the last successful results.`
                        : `Couldn't load service health ${inEnvironment}. Try again shortly.`}
                </LemonBanner>
            ) : (
                !servicesHealthLoading &&
                services.length > 0 && (
                    <LemonBanner type={attentionCount > 0 ? 'warning' : 'success'}>{attentionMessage}</LemonBanner>
                )
            )}
            <LemonInput
                type="search"
                size="small"
                className="max-w-80"
                placeholder="Search services"
                value={search}
                onChange={setSearch}
                data-attr="apm-services-search"
            />
            <LemonTable
                columns={columns}
                dataSource={filteredServices}
                rowKey="service_name"
                loading={servicesHealthLoading}
                emptyState={
                    hasLoadError
                        ? "Couldn't load service health. Check your connection and try again."
                        : services.length > 0
                          ? `No services match "${search}".`
                          : 'No spans in this environment and time range. Send traces to see services here.'
                }
                data-attr="apm-services-table"
            />
        </div>
    )
}
