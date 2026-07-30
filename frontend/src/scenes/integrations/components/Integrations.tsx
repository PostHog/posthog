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
    const { linkedGithubInstallationLoading, githubAvailableInstallations } = useValues(integrationsLogic)
    const { linkExistingGithubInstallation } = useActions(integrationsLogic)
    const githubIntegrations = useIntegrations('github')

    const settingsPath = next ?? urls.settings('environment-integrations')
    const authorizationUrl = api.integrations.authorizeUrl({
        next: currentTeam?.id ? urls.project(currentTeam.id, settingsPath) : settingsPath,
        kind: 'github',
    })

    const installations = githubAvailableInstallations ?? []
    // A GitHub App installs once per org, so reuse an existing installation rather than reinstall —
    // but only when this project has none and the org has one to link.
    const canLinkExisting = githubIntegrations.length === 0 && installations.length > 0
    const multipleInstallations = installations.length > 1

    return (
        <Integration kind="github">
            <div className="flex flex-col gap-y-2">
                <div className="flex flex-wrap gap-2">
                    <LemonButton type="secondary" disableClientSideRouting to={authorizationUrl}>
                        Connect organization
                    </LemonButton>
                    {canLinkExisting &&
                        (multipleInstallations ? (
                            installations.map((installation) => (
                                <LemonButton
                                    key={installation.installation_id}
                                    type="secondary"
                                    loading={linkedGithubInstallationLoading}
                                    onClick={() => linkExistingGithubInstallation(installation.installation_id)}
                                >
                                    Link {installation.account_name ?? `installation ${installation.installation_id}`}
                                </LemonButton>
                            ))
                        ) : (
                            <LemonButton
                                type="secondary"
                                loading={linkedGithubInstallationLoading}
                                onClick={() => linkExistingGithubInstallation()}
                            >
                                Link existing installation
                            </LemonButton>
                        ))}
                </div>
                {canLinkExisting && (
                    <p className="text-secondary text-xs mb-0">
                        {multipleInstallations
                            ? 'Your organization has more than one PostHog GitHub App installation. A GitHub App installs once per organization, so pick the one to connect to this project.'
                            : 'Already installed the PostHog GitHub App for another project in this organization? A GitHub App installs once per organization, so use "Link existing installation" to connect it here instead of reinstalling.'}
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
