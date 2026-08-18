import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { IntegrationView } from 'lib/integrations/IntegrationView'
import { getIntegrationConfig } from 'lib/integrations/organizationIntegrationConfig'

import { IntegrationType } from '~/types'

import { organizationIntegrationsLogic } from './organizationIntegrationsLogic'

export function OrganizationIntegrations(): JSX.Element | null {
    const { organizationIntegrations, organizationIntegrationsLoading, organizationIntegrationsError } =
        useValues(organizationIntegrationsLogic)
    const { loadOrganizationIntegrations } = useActions(organizationIntegrationsLogic)

    if (organizationIntegrationsLoading) {
        return (
            <div className="space-y-2">
                <LemonSkeleton className="h-16" />
                <LemonSkeleton className="h-16" />
            </div>
        )
    }

    if (organizationIntegrationsError) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadOrganizationIntegrations() }}>
                Couldn't load your organization's integrations. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }

    if (!organizationIntegrations || organizationIntegrations.length === 0) {
        return null
    }

    return (
        <div className="space-y-2">
            {organizationIntegrations.map((integration: IntegrationType) => {
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
