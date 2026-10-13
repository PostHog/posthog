import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'

import { IntegrationKind } from '~/types'

export function IntegrationsList({
    titleText = 'All connected integrations are listed here. These integrations may be used for various purposes, such as data warehouse or pipeline destinations. To connect a new integration, visit the relevant product area.',
    onlyKinds,
    omitKinds,
    emptyState,
}: {
    onlyKinds?: IntegrationKind[]
    omitKinds?: IntegrationKind[]
    titleText?: string
    /** Rendered once the list has loaded and nothing matches. */
    emptyState?: JSX.Element
}): JSX.Element {
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { startPolling, stopPolling } = useActions(integrationsLogic)

    useOnMountEffect(() => {
        startPolling()
        return () => stopPolling()
    })
    const filteredIntegrations = integrations?.filter((integration) => {
        if (onlyKinds && !onlyKinds.includes(integration.kind)) {
            return false
        }
        if (omitKinds && omitKinds.includes(integration.kind)) {
            return false
        }
        return true
    })

    return (
        <div>
            {titleText ? <p>{titleText}</p> : null}

            <div className="deprecated-space-y-2">
                {filteredIntegrations?.length ? (
                    filteredIntegrations.map((integration) => (
                        <IntegrationView key={integration.id} integration={integration} />
                    ))
                ) : integrationsLoading || integrations === null ? (
                    <LemonSkeleton className="h-10" />
                ) : (
                    emptyState
                )}
            </div>
        </div>
    )
}
