import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { IconOpenInNew } from 'lib/lemon-ui/icons'

import { IntegrationType } from '~/types'

import { organizationIntegrationsLogic } from './organizationIntegrationsLogic'

function VercelIntegrationSuffix({
    integration,
    onDelete,
    disabledReason,
}: {
    integration: IntegrationType
    onDelete: () => void
    disabledReason?: string
}): JSX.Element {
    const accountUrl = integration.config?.account?.url
    const accountName = integration.config?.account?.name

    return (
        <div className="flex gap-2">
            {accountUrl && (
                <LemonButton
                    type="secondary"
                    to={accountUrl}
                    targetBlank
                    sideIcon={<IconOpenInNew />}
                    tooltip={accountName ? `Open ${accountName} in Vercel` : 'Open in Vercel'}
                >
                    View in Vercel
                </LemonButton>
            )}
            <LemonButton
                type="secondary"
                status="danger"
                onClick={onDelete}
                disabledReason={disabledReason}
                tooltip={disabledReason}
            >
                Disconnect
            </LemonButton>
        </div>
    )
}

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
                        const isVercel = integration.kind === 'vercel'
                        const accountName = integration.config?.account?.name

                        return (
                            <IntegrationView
                                key={integration.id}
                                integration={{
                                    ...integration,
                                    display_name: isVercel && accountName ? accountName : integration.display_name,
                                }}
                                suffix={
                                    isVercel ? (
                                        <VercelIntegrationSuffix
                                            integration={integration}
                                            onDelete={() => deleteIntegration(integration.id)}
                                            disabledReason={restrictionReason || undefined}
                                        />
                                    ) : (
                                        <LemonButton
                                            type="secondary"
                                            status="danger"
                                            onClick={() => deleteIntegration(integration.id)}
                                            disabledReason={restrictionReason || undefined}
                                        >
                                            Disconnect
                                        </LemonButton>
                                    )
                                }
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
