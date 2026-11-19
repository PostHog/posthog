import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect } from '@posthog/lemon-ui'

import { deploymentsLogic } from './deploymentsLogic'
import { DeploymentVersionsTable } from './DeploymentVersionsTable'

export function DeploymentsTab(): JSX.Element {
    const {
        deployments,
        deploymentsLoading,
        deploymentsLoadError,
        deploymentsService,
        serviceNames,
        versionsNewestFirst,
        servicesHealthLoading,
        hasLoadError,
    } = useValues(deploymentsLogic)
    const { setDeploymentsService, requestReload } = useActions(deploymentsLogic)
    const servicesFailed = hasLoadError && !deploymentsService
    const servicesPending = servicesHealthLoading && !deploymentsService
    let emptyState: React.ReactNode = <NoVersionsEmptyState />
    if (servicesFailed) {
        emptyState = "Couldn't load services."
    } else if (servicesPending) {
        emptyState = 'Loading services.'
    } else if (deploymentsService && !deployments) {
        emptyState = 'Loading versions.'
    }

    return (
        <div className="flex flex-col gap-2">
            {servicesFailed ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: () => requestReload(), 'data-attr': 'apm-deployments-retry' }}
                >
                    Couldn't load services, so there's no service to show versions for.
                </LemonBanner>
            ) : (
                deploymentsLoadError && (
                    <LemonBanner type="error">Couldn't load versions. Try again shortly.</LemonBanner>
                )
            )}
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    size="small"
                    value={deploymentsService}
                    onChange={(value) => setDeploymentsService(value)}
                    options={serviceNames.map((name) => ({ value: name, label: name }))}
                    placeholder="Pick a service"
                    data-attr="apm-deployments-service"
                />
                <span className="text-xs text-secondary">
                    {deployments?.version_source === 'k8s.replicaset.name'
                        ? 'Versions from Kubernetes replica sets, because these spans have no service.version. Changes compare with the version before it.'
                        : 'One row per service.version seen in the time range. Changes compare with the version before it.'}
                </span>
            </div>
            <DeploymentVersionsTable
                versions={versionsNewestFirst}
                loading={deploymentsLoading || servicesPending}
                emptyState={emptyState}
                dataAttr="apm-deployments-table"
            />
        </div>
    )
}

function NoVersionsEmptyState(): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-1 text-center">
            <span>No versions in this time range.</span>
            <span className="text-secondary">
                Versions come from the service.version resource attribute, or from k8s.replicaset.name on Kubernetes. To
                set service.version, add it to your OpenTelemetry resource attributes:
            </span>
            <code className="font-mono text-xs">OTEL_RESOURCE_ATTRIBUTES=service.version=1.4.2</code>
        </div>
    )
}
