import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { getIntegrationNameFromKind } from 'lib/integrations/utils'
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
    const { getIntegrationsByKind } = useValues(integrationsLogic)

    const name = getIntegrationNameFromKind(kind)
    const integrations = getIntegrationsByKind([kind])

    const authorizationUrl = api.integrations.authorizeUrl({
        next: urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' }),
        kind,
    })

    return (
        <div className="flex flex-col">
            <h3>{name}</h3>
            <div className="flex flex-col gap-y-2">
                {integrations?.map((integration) => (
                    <IntegrationView key={integration.id} integration={integration} />
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
