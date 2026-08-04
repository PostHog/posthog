import { useActions, useValues } from 'kea'
import { PropsWithChildren, useMemo, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { GitLabSetupModal } from 'scenes/integrations/gitlab/GitLabSetupModal'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { IntegrationKind, IntegrationType } from '~/types'

import type { GitHubAvailableInstallationApi } from 'products/integrations/frontend/generated/api.schemas'

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
    const { linkExistingGithubInstallation, loadGithubAvailableInstallations } = useActions(integrationsLogic)
    const githubIntegrations = useIntegrations('github')

    // integrationsLogic is a singleton mounted from dozens of unrelated surfaces, so this fetch
    // hangs off the GitHub setup UI instead of the shared integrations load.
    useOnMountEffect(() => {
        loadGithubAvailableInstallations()
    })

    const settingsPath = next ?? urls.settings('environment-integrations')
    const authorizationUrl = api.integrations.authorizeUrl({
        next: currentTeam?.id ? urls.project(currentTeam.id, settingsPath) : settingsPath,
        kind: 'github',
    })

    const installations = githubAvailableInstallations ?? []
    const isConnected = githubIntegrations.length > 0
    const canLinkExisting = !isConnected && installations.length > 0
    const multipleInstallations = installations.length > 1

    return (
        <Integration kind="github">
            <div className="flex flex-col gap-y-2">
                <div className="flex flex-wrap gap-2">
                    {/* This leaves PostHog entirely, and a GitHub App installs at most once per
                        account, so GitHub offers install where it's missing and configure where it
                        isn't. Connecting is only a promise we can keep while this project has
                        nothing linked; past that the honest label is the destination. */}
                    <LemonButton type="secondary" disableClientSideRouting to={authorizationUrl}>
                        {isConnected ? 'Manage on GitHub' : 'Connect organization'}
                    </LemonButton>
                    {canLinkExisting && (
                        <GitHubInstallationLink
                            installations={installations}
                            loading={linkedGithubInstallationLoading}
                            onLink={linkExistingGithubInstallation}
                        />
                    )}
                </div>
                {isConnected && (
                    <p className="text-secondary text-xs mb-0">
                        Install the PostHog app on another GitHub account, or change which repositories this
                        installation can see.
                    </p>
                )}
                {canLinkExisting && (
                    <p className="text-secondary text-xs mb-0">
                        {multipleInstallations
                            ? 'Choose an existing GitHub installation to connect to this project.'
                            : 'A GitHub App installs once per organization. Link the installation you already have instead of reinstalling.'}
                    </p>
                )}
            </div>
        </Integration>
    )
}

export function GitHubInstallationLink({
    installations,
    loading,
    onLink,
}: {
    installations: GitHubAvailableInstallationApi[]
    loading: boolean
    onLink: (installationId?: string) => void
}): JSX.Element | null {
    if (installations.length === 0) {
        return null
    }

    if (installations.length === 1) {
        return (
            <LemonButton type="secondary" loading={loading} onClick={() => onLink()}>
                Link existing installation
            </LemonButton>
        )
    }

    return (
        <LemonMenu
            items={installations.map((installation) => ({
                key: installation.installation_id,
                label: installation.account_name ?? `Installation ${installation.installation_id}`,
                disabledReason: loading ? 'Linking an installation' : undefined,
                onClick: () => onLink(installation.installation_id),
            }))}
        >
            <LemonButton type="secondary" loading={loading} sideIcon={<IconChevronDown />}>
                Link existing installation
            </LemonButton>
        </LemonMenu>
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
