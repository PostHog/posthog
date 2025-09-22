import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

import { IntegrationKind } from '~/types'

export function LinearIntegration(): JSX.Element {
    return <Integration kind="linear" connectText="Connect workspace" />
}

export function GithubIntegration(): JSX.Element {
    return <Integration kind="github" connectText="Connect GitHub" />
}

const Integration = ({ kind, connectText }: { kind: IntegrationKind; connectText: string }): JSX.Element => {
    const { getIntegrationsByKind } = useValues(integrationsLogic)

    const integrations = getIntegrationsByKind([kind])

    const authorizationUrl = api.integrations.authorizeUrl({
        next: urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' }),
        kind,
    })

    return (
        <div className="flex flex-col">
            <div className="flex flex-col gap-y-2">
                {integrations?.map((integration) => (
                    <IntegrationView key={integration.id} integration={integration} />
                ))}
                <div className="flex">
                    <LemonButton type="secondary" disableClientSideRouting to={authorizationUrl}>
                        {connectText}
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
