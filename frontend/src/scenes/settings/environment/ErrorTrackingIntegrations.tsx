import { IconTrash } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { urls } from 'scenes/urls'
import { IntegrationKind } from '~/types'

export function ErrorTrackingIntegrations(): JSX.Element {
    return (
        <div className="flex flex-col gap-y-6">
            <Integration kind="github" />
            <Integration kind="linear" />
        </div>
    )
}

const Integration = ({ kind }: { kind: IntegrationKind }): JSX.Element => {
    const { deleteIntegration } = useActions(integrationsLogic)
    const { getIntegrationsByKind } = useValues(integrationsLogic)

    const name = getIntegrationNameFromKind(kind)
    const integrations = getIntegrationsByKind([kind])

    const authorizationUrl = api.integrations.authorizeUrl({
        next: urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' }),
        kind,
    })

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
                    <LemonButton type="secondary" disableClientSideRouting to={authorizationUrl}>
                        Connect workspace
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
