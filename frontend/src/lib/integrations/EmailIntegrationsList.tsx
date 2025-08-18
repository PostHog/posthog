import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { IntegrationEmailDomainView } from './IntegrationEmailDomainView'

export function EmailIntegrationsList(): JSX.Element {
    const { integrationsLoading, domainGroupedEmailIntegrations } = useValues(integrationsLogic)

    return (
        <div className="deprecated-space-y-2">
            {integrationsLoading ? (
                <LemonSkeleton className="h-10" />
            ) : (
                domainGroupedEmailIntegrations.map((integration) => (
                    <IntegrationEmailDomainView key={integration.domain} integration={integration} />
                ))
            )}
        </div>
    )
}
