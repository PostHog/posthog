import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import type { ServiceHealthApi } from './generated/api.schemas'
import { healthColumns } from './healthColumns'
import { Sparkline } from './Sparkline'
import { TelemetryLinks } from './TelemetryLinks'

export function ServicesTab(): JSX.Element {
    const { services, servicesHealthLoading, hasLoadError, resolvedEnvironment, timeRange, attentionCount } =
        useValues(applicationObservabilityLogic)
    const { showServiceEndpoints } = useActions(applicationObservabilityLogic)

    const columns: LemonTableColumns<ServiceHealthApi> = [
        {
            title: 'Service',
            key: 'service_name',
            render: (_, row) => <span className="font-semibold">{row.service_name}</span>,
        },
        ...healthColumns<ServiceHealthApi>(),
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
                    <TelemetryLinks serviceName={row.service_name} timeRange={timeRange} />
                </span>
            ),
        },
    ]

    const attentionMessage =
        attentionCount > 0
            ? `${attentionCount} ${attentionCount === 1 ? 'service needs' : 'services need'} attention in ${resolvedEnvironment}`
            : `All quiet in ${resolvedEnvironment}`

    return (
        <div className="flex flex-col gap-2">
            {hasLoadError ? (
                <LemonBanner type="error">
                    {services.length > 0
                        ? `Couldn't refresh service health for ${resolvedEnvironment}. Showing the last successful results.`
                        : `Couldn't load service health for ${resolvedEnvironment}. Try again shortly.`}
                </LemonBanner>
            ) : (
                !servicesHealthLoading &&
                services.length > 0 && (
                    <LemonBanner type={attentionCount > 0 ? 'warning' : 'success'}>{attentionMessage}</LemonBanner>
                )
            )}
            <LemonTable
                columns={columns}
                dataSource={services}
                rowKey="service_name"
                loading={servicesHealthLoading}
                emptyState={
                    hasLoadError
                        ? "Couldn't load service health. Check your connection and try again."
                        : 'No spans in this environment and time range. Send traces to see services here.'
                }
                data-attr="apm-services-table"
            />
        </div>
    )
}
