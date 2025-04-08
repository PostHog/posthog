import { IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

export function ErrorTrackingIntegration(): JSX.Element {
    const { linearIntegrations } = useValues(integrationsLogic)
    const { deleteIntegration } = useActions(integrationsLogic)

    const onDeleteClick = (id: number): void => {
        LemonDialog.open({
            title: 'Do you want to disconnect from Linear?',
            description:
                'This cannot be undone. PostHog resources configured to use this Linear workspace will remain but will stop working.',
            primaryButton: {
                children: 'Yes, disconnect',
                status: 'danger',
                onClick: () => {
                    if (id) {
                        deleteIntegration(id)
                    }
                },
            },
            secondaryButton: {
                children: 'No thanks',
            },
        })
    }

    return (
        <div>
            <div className="gap-y-2">
                {linearIntegrations?.map((integration) => (
                    <IntegrationView
                        key={integration.id}
                        integration={integration}
                        suffix={
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={() => onDeleteClick(integration.id)}
                                icon={<IconTrash />}
                            >
                                Disconnect
                            </LemonButton>
                        }
                    />
                ))}

                <div className="flex">
                    <LemonButton
                        type="secondary"
                        to={api.integrations.authorizeUrl({ kind: 'linear' })}
                        disableClientSideRouting
                    >
                        Connect <>{linearIntegrations?.length > 0 ? 'another' : 'a'}</> Linear workspace
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
