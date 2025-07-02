import { IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { urls } from 'scenes/urls'
import { IntegrationType } from '~/types'

type Integration = {
    name: 'Linear' | 'GitHub'
    kind: 'linear' | 'github'
    integrations: IntegrationType[]
}

export function ErrorTrackingIntegrations(): JSX.Element {
    const { linearIntegrations, githubIntegrations } = useValues(integrationsLogic)

    const integrations: Integration[] = [
        {
            name: 'GitHub',
            kind: 'github',
            integrations: githubIntegrations,
        },
        {
            name: 'Linear',
            kind: 'linear',
            integrations: linearIntegrations,
        },
    ]

    return (
        <div className="flex flex-col gap-y-6">
            {integrations.map((integration) => (
                <Integration integration={integration} />
            ))}
        </div>
    )
}

const Integration = ({ integration: { name, kind, integrations } }: { integration: Integration }): JSX.Element => {
    const { deleteIntegration } = useActions(integrationsLogic)

    const onDeleteClick = (id: number): void => {
        LemonDialog.open({
            title: `Do you want to disconnect from ${name}?`,
            description: `This cannot be undone. PostHog resources configured to use this ${name} workspace will remain but will stop working.`,
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
        <div className="flex flex-col">
            <h3>{name}</h3>
            <div className="flex flex-col gap-y-2">
                {integrations?.map((integration) => (
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
                            kind,
                            next: urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' }),
                        })}
                        disableClientSideRouting
                    >
                        Connect <>{integrations?.length > 0 ? 'another' : 'a'}</> {name} workspace
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
