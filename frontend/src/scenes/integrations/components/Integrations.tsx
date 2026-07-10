import { useActions, useValues } from 'kea'
import { PropsWithChildren, useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { GitLabSetupModal } from 'scenes/integrations/gitlab/GitLabSetupModal'
import { teamLogic } from 'scenes/teamLogic'
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

export function LinearIntegration({ next }: { next?: string }): JSX.Element {
    return <OAuthIntegration kind="linear" connectText="Connect workspace" next={next} />
}

export function GithubIntegration({ next }: { next?: string }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { linkedGithubInstallationLoading } = useValues(integrationsLogic)
    const { linkExistingGithubInstallation } = useActions(integrationsLogic)
    const githubIntegrations = useIntegrations('github')

    const settingsPath = next ?? urls.settings('environment-integrations')
    const authorizationUrl = api.integrations.authorizeUrl({
        next: currentTeam?.id ? urls.project(currentTeam.id, settingsPath) : settingsPath,
        kind: 'github',
    })

    return (
        <Integration kind="github">
            <div className="flex flex-col gap-y-2">
                <div className="flex gap-x-2">
                    <LemonButton type="secondary" disableClientSideRouting to={authorizationUrl}>
                        Connect organization
                    </LemonButton>
                    {githubIntegrations.length === 0 && (
                        <LemonButton
                            type="secondary"
                            loading={linkedGithubInstallationLoading}
                            onClick={() => linkExistingGithubInstallation()}
                        >
                            Link existing installation
                        </LemonButton>
                    )}
                </div>
                {githubIntegrations.length === 0 && (
                    <p className="text-secondary text-xs mb-0">
                        Already installed the PostHog GitHub App for another project in this organization? A GitHub App
                        installs once per organization, so use "Link existing installation" to connect it here instead
                        of reinstalling.
                    </p>
                )}
            </div>
        </Integration>
    )
}

export function JiraIntegration({ next }: { next?: string }): JSX.Element {
    return <OAuthIntegration kind="jira" connectText="Connect site" next={next} />
}

const OAuthIntegration = ({
    kind,
    connectText,
    next,
}: {
    kind: IntegrationKind
    connectText: string
    next?: string
}): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const settingsPath = next ?? urls.settings('environment-integrations')
    const authorizationUrl = api.integrations.authorizeUrl({
        next: currentTeam?.id ? urls.project(currentTeam.id, settingsPath) : settingsPath,
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
