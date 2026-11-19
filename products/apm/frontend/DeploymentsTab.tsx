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
    let emptyState = 'No versions in this time range. Set service.version on your spans to see deployments.'
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
                    One row per service.version seen in the time range. Changes compare with the version before it.
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
