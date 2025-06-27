import { IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

export function ErrorTrackingIntegrations(): JSX.Element {
    const { linearIntegrations, githubIntegrations } = useValues(integrationsLogic)
    const { deleteIntegration } = useActions(integrationsLogic)

    const onDeleteClick = (id: number): void => {
        LemonDialog.open({
            title: 'Do you want to disconnect from Linear?',
            description:
                'This cannot be undone. PostHog resources configured to use this Linear workspace will remain but will stop working.',
            primaryButton: {
                children: 'Yes, disconnect',
                status: 'danger',
                onClick: () => deleteIntegration(id),
            },
            secondaryButton: {
                children: 'No thanks',
            },
        })
    }

    return (
        <div className="flex flex-col gap-y-2">
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
            {githubIntegrations?.map((integration) => (
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
                    to={api.integrations.authorizeUrl({
                        kind: 'linear',
                        next: router.values.currentLocation.pathname,
                    })}
                    disableClientSideRouting
                >
                    Connect <>{linearIntegrations?.length > 0 ? 'another' : 'a'}</> Linear workspace
                </LemonButton>
            </div>
            <div className="flex">
                <LemonButton
                    type="secondary"
                    to={api.integrations.authorizeUrl({
                        kind: 'github',
                        next: router.values.currentLocation.pathname,
                    })}
                    disableClientSideRouting
                >
                    Connect <>{githubIntegrations?.length > 0 ? 'another' : 'a'}</> GitHub organization
                </LemonButton>
            </div>
        </div>
    )
}
