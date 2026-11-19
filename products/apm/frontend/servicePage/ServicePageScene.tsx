import { useActions, useValues } from 'kea'

import { IconArrowUpRight } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { endpointOperationUrl } from '../endpointOperationUrl'
import type { EndpointHealthApi } from '../generated/api.schemas'
import { healthColumns } from '../healthColumns'
import { formatMs, formatPercent, formatRate } from '../healthDisplay'
import { HealthStatusTag } from '../HealthStatusTag'
import { HealthTableLink } from '../HealthTableLink'
import { Sparkline } from '../Sparkline'
import { TelemetryLinks } from '../TelemetryLinks'
import { ServiceLatencyChart } from './ServiceLatencyChart'
import { readScopeParam, serviceTracesUrl } from './servicePage'
import { ERROR_SAMPLE_LIMIT, servicePageLogic, ServicePageLogicProps } from './servicePageLogic'
import { ServiceRequestsChart } from './ServiceRequestsChart'
import { ServiceScopeSelectors } from './ServiceScopeSelectors'
import { ServiceSection } from './ServiceSection'
import { ServiceTopErrors } from './ServiceTopErrors'

export const scene: SceneExport<ServicePageLogicProps> = {
    component: ServicePageScene,
    logic: servicePageLogic,
    paramsToProps: ({ searchParams: { service } }) => ({ serviceName: readScopeParam(service) ?? '' }),
}

// Pinned: the ids are URL fragments people share.
const SECTIONS = [
    { id: 'summary', title: 'Summary' },
    { id: 'endpoints', title: 'Endpoints' },
    { id: 'errors', title: 'Errors' },
    { id: 'traces', title: 'Traces' },
    { id: 'logs', title: 'Logs' },
] as const

function StatBlock({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="text-xs text-muted">{label}</span>
            <span className="font-mono text-sm">{value}</span>
        </div>
    )
}

function ChartLoadError({ onRetry }: { onRetry: () => void }): JSX.Element {
    return (
        <div className="h-48 flex items-center">
            <LemonBanner type="error" className="w-full" action={{ children: 'Retry', onClick: () => onRetry() }}>
                Couldn't load this chart.
            </LemonBanner>
        </div>
    )
}

function ServiceTableOfContents(): JSX.Element {
    return (
        <nav
            className="hidden @min-[48rem]/main-content:flex flex-col gap-px sticky top-0 self-start w-32 shrink-0 pt-2"
            aria-label="Service page sections"
        >
            {SECTIONS.map(({ id, title }) => (
                <LemonButton
                    key={id}
                    size="small"
                    type="tertiary"
                    fullWidth
                    onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                    data-attr={`apm-service-toc-${id}`}
                >
                    {title}
                </LemonButton>
            ))}
        </nav>
    )
}

export function ServicePageScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        serviceName,
        timeRange,
        dateRange,
        scope,
        scopeFilters,
        service,
        servicesHealthLoading,
        servicesHealthFailed,
        endpoints,
        endpointsHealthLoading,
        endpointsHealthFailed,
        requestsSeries,
        requestsSeriesLoading,
        requestsSeriesFailed,
        latencyHeatmapData,
        latencyPercentiles,
        rawLatencyHeatmapLoading,
        rawLatencyHeatmapFailed,
        topErrors,
        errorSpans,
        errorSpansLoading,
        errorSpansFailed,
        statusCodeErrors,
        statusCodeErrorsLoading,
        statusCodeErrorsFailed,
    } = useValues(servicePageLogic)
    const {
        fetchServicesHealth,
        fetchEndpointsHealth,
        fetchRequestsSeries,
        fetchLatencyHeatmap,
        fetchStatusCodeErrors,
        fetchErrorSpans,
    } = useActions(servicePageLogic)

    if (!featureFlags[FEATURE_FLAGS.APPLICATION_OBSERVABILITY]) {
        return <NotFound object="page" />
    }

    if (!serviceName) {
        return (
            <SceneContent>
                <div className="flex flex-col items-center gap-1 py-16">
                    <span>This link is missing a service name.</span>
                    <Link to={urls.applicationObservability()}>Back to application observability</Link>
                </div>
            </SceneContent>
        )
    }

    const endpointColumns: LemonTableColumns<EndpointHealthApi> = [
        {
            title: 'Endpoint',
            key: 'endpoint',
            render: (_, row) => (
                <HealthTableLink to={endpointOperationUrl(row, dateRange)} data-attr="apm-service-endpoint-operation">
                    {row.endpoint}
                </HealthTableLink>
            ),
        },
        ...healthColumns<EndpointHealthApi>(endpoints),
    ]

    return (
        <SceneContent>
            <SceneTitleSection
                name={serviceName}
                description={null}
                resourceType={{ type: 'tracing' }}
                forceBackTo={{
                    key: 'application-observability',
                    name: 'Application observability',
                    path: urls.applicationObservability(),
                }}
            />
            <div className="flex flex-wrap items-center gap-3">
                {service ? (
                    <span data-attr="apm-service-health">
                        <HealthStatusTag status={service.status} />
                    </span>
                ) : null}
                <ServiceScopeSelectors serviceName={serviceName} />
            </div>
            <div className="flex gap-6 items-start">
                <ServiceTableOfContents />
                <div className="flex flex-col gap-6 flex-1 min-w-0">
                    <ServiceSection id="summary" title="Summary">
                        {servicesHealthFailed && !servicesHealthLoading ? (
                            <LemonBanner
                                type="error"
                                action={{ children: 'Retry', onClick: () => fetchServicesHealth() }}
                            >
                                Couldn't load this service's health.
                            </LemonBanner>
                        ) : (
                            <div className="flex flex-wrap items-end gap-8" data-attr="apm-service-stats">
                                <StatBlock
                                    label="Requests"
                                    value={service ? service.health.span_count.toLocaleString() : '—'}
                                />
                                <StatBlock
                                    label="Request rate"
                                    value={formatRate(service?.health.request_rate ?? null)}
                                />
                                <StatBlock
                                    label="Errors"
                                    value={service ? service.health.error_count.toLocaleString() : '—'}
                                />
                                <StatBlock
                                    label="Error rate"
                                    value={formatPercent(service?.health.error_rate ?? null)}
                                />
                                <StatBlock label="p95" value={formatMs(service?.health.p95_ms ?? null)} />
                                {service && <Sparkline values={service.sparkline} />}
                                {!service && !servicesHealthLoading && (
                                    <span className="text-xs text-muted">
                                        No requests in this environment and range.
                                    </span>
                                )}
                            </div>
                        )}
                        {(scope.version || scope.operation) && (
                            <span className="text-xs text-muted">
                                These totals cover the whole service in the selected environment. The charts below
                                follow the version and operation you picked.
                            </span>
                        )}
                        <div className="grid grid-cols-1 @min-[64rem]/main-content:grid-cols-2 gap-4">
                            <div className="flex flex-col gap-1">
                                <span className="text-sm font-semibold">Requests and errors</span>
                                {requestsSeriesFailed && !requestsSeriesLoading ? (
                                    <ChartLoadError onRetry={() => fetchRequestsSeries()} />
                                ) : (
                                    <ServiceRequestsChart data={requestsSeries} loading={requestsSeriesLoading} />
                                )}
                            </div>
                            <div className="flex flex-col gap-1">
                                <span className="text-sm font-semibold">Latency</span>
                                {rawLatencyHeatmapFailed && !rawLatencyHeatmapLoading ? (
                                    <ChartLoadError onRetry={() => fetchLatencyHeatmap()} />
                                ) : (
                                    <ServiceLatencyChart
                                        timeBuckets={latencyHeatmapData.timeBuckets}
                                        percentiles={latencyPercentiles}
                                        loading={rawLatencyHeatmapLoading}
                                    />
                                )}
                                <span className="text-xs text-muted">
                                    Each point is the top of the latency bucket the percentile falls in.
                                </span>
                            </div>
                        </div>
                    </ServiceSection>
                    <ServiceSection id="endpoints" title="Endpoints">
                        {endpointsHealthFailed && !endpointsHealthLoading ? (
                            <LemonBanner
                                type="error"
                                action={{ children: 'Retry', onClick: () => fetchEndpointsHealth() }}
                            >
                                Couldn't load endpoints.
                            </LemonBanner>
                        ) : (
                            <LemonTable
                                columns={endpointColumns}
                                dataSource={endpoints}
                                rowKey="endpoint"
                                loading={endpointsHealthLoading}
                                emptyState="No endpoints in this environment and range."
                                data-attr="apm-service-endpoints-table"
                            />
                        )}
                    </ServiceSection>
                    <ServiceSection id="errors" title="Errors">
                        <ServiceTopErrors
                            topErrors={topErrors}
                            topErrorsLoading={errorSpansLoading || statusCodeErrorsLoading}
                            sampleSize={errorSpans.length}
                            sampleLimit={ERROR_SAMPLE_LIMIT}
                            statusCodeErrors={statusCodeErrors}
                            failed={errorSpansFailed || statusCodeErrorsFailed}
                            onRetry={() => {
                                if (errorSpansFailed) {
                                    fetchErrorSpans()
                                }
                                if (statusCodeErrorsFailed) {
                                    fetchStatusCodeErrors()
                                }
                            }}
                        />
                    </ServiceSection>
                    <ServiceSection id="traces" title="Traces">
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                sideIcon={<IconArrowUpRight />}
                                to={serviceTracesUrl(serviceName, dateRange, scopeFilters)}
                                data-attr="apm-service-traces-link"
                            >
                                View traces
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                size="small"
                                sideIcon={<IconArrowUpRight />}
                                to={serviceTracesUrl(serviceName, dateRange, scopeFilters, { errorsOnly: true })}
                                data-attr="apm-service-error-traces-link"
                            >
                                View error traces
                            </LemonButton>
                        </div>
                    </ServiceSection>
                    <ServiceSection id="logs" title="Logs">
                        <span className="flex flex-wrap gap-3">
                            <TelemetryLinks
                                serviceName={serviceName}
                                timeRange={timeRange}
                                source="service-page"
                                signals={['logs', 'metrics']}
                            />
                        </span>
                    </ServiceSection>
                </div>
            </div>
        </SceneContent>
    )
}

export default ServicePageScene
