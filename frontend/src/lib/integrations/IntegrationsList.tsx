import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'

import { IntegrationKind } from '~/types'
import { IntegrationEmailDomainView } from './IntegrationEmailDomainView'

export function IntegrationsList({
    integrationKinds,
    titleText = 'All connected integrations are listed here. These integrations may be used for various purposes, such as data warehouse or pipeline destinations. To connect a new integration, visit the relevant product area.',
}: {
    integrationKinds: IntegrationKind[]
    titleText?: string
}): JSX.Element {
    const { integrations, integrationsLoading, domainGroupedEmailIntegrations } = useValues(integrationsLogic)
    const filteredIntegrations = integrations?.filter((integration) => integrationKinds.includes(integration.kind))

    return (
        <div>
            {titleText ? <p>{titleText}</p> : null}

            <div className="deprecated-space-y-2">
                {domainGroupedEmailIntegrations?.length
                    ? domainGroupedEmailIntegrations.map((integration) => (
                          <IntegrationEmailDomainView key={integration.domain} integration={integration} />
                      ))
                    : null}
                {filteredIntegrations?.length ? (
                    filteredIntegrations.map((integration) => (
                        <IntegrationView key={integration.id} integration={integration} />
                    ))
                ) : integrationsLoading ? (
                    <LemonSkeleton className="h-10" />
                ) : (
                    <p>No integrations</p>
                )}
            </div>
        </div>
    )
}
