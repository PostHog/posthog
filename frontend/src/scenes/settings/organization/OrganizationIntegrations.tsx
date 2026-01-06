import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { IntegrationView } from 'lib/integrations/IntegrationView'
import { getIntegrationConfig } from 'lib/integrations/organizationIntegrationConfig'

import { organizationIntegrationsLogic } from './organizationIntegrationsLogic'

export function OrganizationIntegrations(): JSX.Element | null {
    const { organizationIntegrations, organizationIntegrationsLoading } = useValues(organizationIntegrationsLogic)

    if (organizationIntegrationsLoading) {
        return (
            <div className="space-y-2">
                <LemonSkeleton className="h-16" />
                <LemonSkeleton className="h-16" />
            </div>
        )
    }

    if (!organizationIntegrations || organizationIntegrations.length === 0) {
        return null
    }

    return (
        <div className="space-y-2">
            {organizationIntegrations.map((integration) => {
                const config = getIntegrationConfig(integration.kind)

                return (
                    <IntegrationView
                        key={integration.id}
                        integration={{
                            ...integration,
                            display_name: config.getDisplayName(integration),
                        }}
                        suffix={config.getSuffix(integration)}
                    />
                )
            })}
        </div>
    )
}
