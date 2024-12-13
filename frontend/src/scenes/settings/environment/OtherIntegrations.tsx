import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import { IntegrationType } from '~/types'

export function OtherIntegrations(): JSX.Element {
    const { integrations, integrationsLoading } = useValues(integrationsLogic)
    const { deleteIntegration } = useActions(integrationsLogic)

    const otherIntegrations = integrations?.filter((integration) => integration.kind !== 'slack')

    const onDeleteClick = (integration: IntegrationType): void => {
        LemonDialog.open({
            title: `Do you want to disconnect from this ${integration.kind} integration?`,
            description:
                'This cannot be undone. PostHog resources configured to use this integration will remain but will stop working.',
            primaryButton: {
                children: 'Yes, disconnect',
                status: 'danger',
                onClick: () => deleteIntegration(integration.id),
            },
            secondaryButton: {
                children: 'No thanks',
            },
        })
    }

    return (
        <div>
            <p>
                All connected integrations are listed here. These integrations may be used for various purposes, such as
                data warehouse or pipeline destinations. To connect a new integration, visit the relevant product area.
            </p>

            <div className="space-y-2">
                {otherIntegrations?.length ? (
                    otherIntegrations.map((integration) => (
                        <IntegrationView
                            key={integration.id}
                            integration={integration}
                            suffix={
                                <LemonButton
                                    type="secondary"
                                    status="danger"
                                    onClick={() => onDeleteClick(integration)}
                                    icon={<IconTrash />}
                                >
                                    Disconnect
                                </LemonButton>
                            }
                        />
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
