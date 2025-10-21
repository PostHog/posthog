import { useValues } from 'kea'
import { PropsWithChildren, useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { GitLabSetupModal } from 'scenes/integrations/gitlab/GitLabSetupModal'
import { urls } from 'scenes/urls'

import { IntegrationKind, IntegrationType } from '~/types'

export function GitLabIntegration(): JSX.Element {
    const [isOpen, setIsOpen] = useState<boolean>(false)
    return (
        <Integration kind="gitlab">
            <LemonButton type="secondary" onClick={() => setIsOpen(true)}>
                Connect project
            </LemonButton>
            <GitLabSetupModal isOpen={isOpen} onComplete={() => setIsOpen(false)} />
        </Integration>
    )
}

export function LinearIntegration(): JSX.Element {
    return <OAuthIntegration kind="linear" connectText="Connect workspace" />
}

export function GithubIntegration(): JSX.Element {
    return <OAuthIntegration kind="github" connectText="Connect organization" />
}

const OAuthIntegration = ({ kind, connectText }: { kind: IntegrationKind; connectText: string }): JSX.Element => {
    const authorizationUrl = api.integrations.authorizeUrl({
        next: urls.errorTrackingConfiguration({ tab: 'error-tracking-integrations' }),
        kind,
    })

    return (
        <Integration kind={kind}>
            <LemonButton type="secondary" disableClientSideRouting to={authorizationUrl}>
                {connectText}
            </LemonButton>
        </Integration>
    )
}

const Integration = ({ kind, children }: PropsWithChildren<{ kind: IntegrationKind }>): JSX.Element => {
    const integrations = useIntegrations(kind)

    return (
        <div className="flex flex-col">
            <div className="flex flex-col gap-y-2">
                {integrations?.map((integration) => (
                    <IntegrationView key={integration.id} integration={integration} />
                ))}
                <div className="flex">{children}</div>
            </div>
        </div>
    )
}

const useIntegrations = (kind: IntegrationKind): IntegrationType[] => {
    const { getIntegrationsByKind } = useValues(integrationsLogic)

    return useMemo(() => getIntegrationsByKind([kind] satisfies IntegrationKind[]), [getIntegrationsByKind, kind])
}
