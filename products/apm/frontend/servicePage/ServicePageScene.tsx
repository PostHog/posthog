import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { formatMs, formatPercent, formatRate } from '../healthDisplay'
import { HealthStatusTag } from '../HealthStatusTag'
import { Sparkline } from '../Sparkline'
import { readScopeParam } from './servicePage'
import { servicePageLogic, ServicePageLogicProps } from './servicePageLogic'
import { ServiceScopeSelectors } from './ServiceScopeSelectors'
import { ServiceSection } from './ServiceSection'

export const scene: SceneExport<ServicePageLogicProps> = {
    component: ServicePageScene,
    logic: servicePageLogic,
    paramsToProps: ({ searchParams: { service } }) => ({ serviceName: readScopeParam(service) ?? '' }),
}

// Pinned: the ids are URL fragments people share.
const SECTIONS = [{ id: 'summary', title: 'Summary' }] as const

function StatBlock({ label, value }: { label: string; value: string }): JSX.Element {
    return (
        <div className="flex flex-col">
            <span className="text-xs text-muted">{label}</span>
            <span className="font-mono text-sm">{value}</span>
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
    const { serviceName, service, servicesHealthLoading, servicesHealthFailed } = useValues(servicePageLogic)
    const { fetchServicesHealth } = useActions(servicePageLogic)

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
                    </ServiceSection>
                </div>
            </div>
        </SceneContent>
    )
}

export default ServicePageScene
