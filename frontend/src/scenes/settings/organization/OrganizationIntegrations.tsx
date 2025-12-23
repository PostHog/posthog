import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { getIntegrationConfig } from 'lib/integrations/organizationIntegrationConfig'

import { organizationIntegrationsLogic } from './organizationIntegrationsLogic'

export function OrganizationIntegrations(): JSX.Element {
    const { organizationIntegrations, organizationIntegrationsLoading } = useValues(organizationIntegrationsLogic)
    const { deleteIntegration } = useActions(organizationIntegrationsLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    return (
        <div className="space-y-4">
            <div>
                <h2 className="subtitle">Organization integrations</h2>
                <p className="text-muted">
                    Integrations that connect to your entire organization for billing, resource management, and other
                    organization-wide features.
                </p>
            </div>

            {organizationIntegrationsLoading ? (
                <div className="space-y-2">
                    <LemonSkeleton className="h-16" />
                    <LemonSkeleton className="h-16" />
                </div>
            ) : organizationIntegrations && organizationIntegrations.length > 0 ? (
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
                                suffix={config.getSuffix(
                                    integration,
                                    () => deleteIntegration(integration.id),
                                    restrictionReason || undefined
                                )}
                            />
                        )
                    })}
                </div>
            ) : (
                <div className="border rounded p-6 text-center space-y-2 bg-bg-light">
                    <h3 className="text-muted-alt mb-2">No organization integrations</h3>
                    <p className="text-muted text-sm max-w-140 mx-auto">
                        Organization integrations like Vercel connect at the organization level for billing and resource
                        management.
                    </p>
                    <p className="text-muted text-sm max-w-140 mx-auto">
                        Install integrations from their respective marketplaces to see them here.
                    </p>
                </div>
            )}
        </div>
    )
}
