import { useValues } from 'kea'
import { PropsWithChildren, useMemo, useState } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { GitLabSetupModal } from 'scenes/integrations/gitlab/GitLabSetupModal'
import { urls } from 'scenes/urls'

import { IntegrationKind, IntegrationType } from '~/types'

export function ReplayIntegrations(): JSX.Element {
    return (
        <div className="flex flex-col gap-y-6">
            <LemonBanner type="info">
                Configure integrations to create and link issues from session replays.
            </LemonBanner>
            <div>
                <h3>Linear</h3>
                <LinearIntegration />
            </div>
            <div>
                <h3>GitHub</h3>
                <GitHubIntegration />
            </div>
            <div>
                <h3>GitLab</h3>
                <GitLabIntegration />
            </div>
            <div>
                <h3>Jira</h3>
                <JiraIntegration />
            </div>
        </div>
    )
}

function LinearIntegration(): JSX.Element {
    return <OAuthIntegration kind="linear" connectText="Connect workspace" />
}

function GitHubIntegration(): JSX.Element {
    return <OAuthIntegration kind="github" connectText="Connect organization" />
}

function GitLabIntegration(): JSX.Element {
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

function JiraIntegration(): JSX.Element {
    return <OAuthIntegration kind="jira" connectText="Connect site" />
}

const OAuthIntegration = ({ kind, connectText }: { kind: IntegrationKind; connectText: string }): JSX.Element => {
    const authorizationUrl = api.integrations.authorizeUrl({
        next: urls.replaySettings('replay-integrations'),
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
