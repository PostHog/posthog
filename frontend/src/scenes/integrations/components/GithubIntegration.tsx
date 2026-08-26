import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { GitHubInstallRequestsBanner } from 'lib/integrations/GitHubInstallRequestsBanner'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import type { IntegrationConnectSurface } from 'lib/integrations/utils'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { GitHubAvailableInstallationApi } from 'products/integrations/frontend/generated/api.schemas'

import { Integration, useIntegrations } from './Integration'

export function GithubIntegration({
    next,
    connectSurface,
}: {
    next?: string
    /**
     * Where this card is rendered, reported as the `surface` on `integration_connect_clicked`.
     * Omit it only on the OAuth landing page, which reports every kind's connect click itself —
     * passing it there would count one click twice. Every other render site should set it.
     */
    connectSurface?: IntegrationConnectSurface
}): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { linkedGithubInstallationLoading, githubAvailableInstallations, githubPersonalConnected } =
        useValues(integrationsLogic)
    const { linkExistingGithubInstallation, loadGithubAvailableInstallations, startPolling, stopPolling } =
        useActions(integrationsLogic)
    const { reportIntegrationConnectClicked } = useActions(eventUsageLogic)
    const githubIntegrations = useIntegrations('github')

    // integrationsLogic is a singleton mounted from dozens of unrelated surfaces, so this fetch
    // hangs off the GitHub setup UI instead of the shared integrations load. Polling is likewise
    // scoped to the settings surface: an uninstall on GitHub should show up while someone is looking.
    useOnMountEffect(() => {
        loadGithubAvailableInstallations()
        startPolling()
        return () => stopPolling()
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

    // Silent without `connectSurface`, because the only card rendered without one sits on the OAuth
    // landing page, which already reports every kind's connect click for itself.
    const reportConnect = (variant?: IntegrationConnectSurface): void => {
        if (connectSurface) {
            reportIntegrationConnectClicked('github', 'github', variant ?? connectSurface)
        }
    }

    return (
        <Integration kind="github">
            {/* w-full because Integration drops its children into a bare flex row, which would
                otherwise size the banner to its longest word. */}
            <div className="flex flex-col gap-y-4 w-full">
                <GitHubInstallRequestsBanner
                    finishConnectingUrl={authorizationUrl}
                    onFinishConnecting={() => reportConnect('install_approved_banner')}
                />
                {/* An install GitHub already has is the exception, not a second way to connect, so it
                    reads as an aside with its own action rather than a button competing with the one
                    below. */}
                {canLinkExisting && (
                    <LemonBanner type="info" hideIcon>
                        <div className="flex items-center gap-3">
                            <span className="min-w-0 text-sm font-normal">
                                {multipleInstallations ? (
                                    <>Already installed on more than one of your GitHub accounts.</>
                                ) : (
                                    <>
                                        Already installed on your GitHub account{' '}
                                        <code>{accountLabel(installations[0])}</code>.
                                    </>
                                )}
                            </span>
                            <GitHubInstallationLink
                                installations={installations}
                                loading={linkedGithubInstallationLoading}
                                onLink={(installationId) => {
                                    // Reusing an existing install never leaves PostHog, so it's a
                                    // connect that skips GitHub entirely — worth separating from the
                                    // clicks that redirect out.
                                    reportConnect('settings_link_existing')
                                    linkExistingGithubInstallation(installationId)
                                }}
                                projectName={currentTeam?.name}
                            />
                        </div>
                    </LemonBanner>
                )}
                <div className="flex flex-wrap gap-2">
                    {/* This leaves PostHog entirely, and a GitHub App installs at most once per
                        account, so GitHub offers install where it's missing and configure where it
                        isn't. "Connect account" matches the Linear and Jira cards, which name the
                        third party's container. */}
                    <LemonButton
                        type="secondary"
                        disableClientSideRouting
                        to={authorizationUrl}
                        onClick={() => reportConnect(isConnected ? 'settings_manage' : undefined)}
                    >
                        {isConnected ? 'Manage on GitHub' : 'Connect account'}
                    </LemonButton>
                </div>
                {isConnected && (
                    <p className="text-secondary text-xs mb-0">
                        Add the PostHog app to another GitHub account, or change which repositories it can see.
                    </p>
                )}
                {!isConnected && installations.length === 0 && githubPersonalConnected === false && (
                    <p className="text-secondary text-xs mb-0">
                        Already installed the PostHog GitHub App but don't see it here? Connect your GitHub account
                        under <Link to={urls.settings('user-personal-integrations')}>Personal integrations</Link> so
                        PostHog can find it.
                    </p>
                )}
            </div>
        </Integration>
    )
}

// The GitHub account name is what a person recognizes, so it carries the label wherever we have
// it. The id is a fallback for an installation whose account metadata never arrived.
function accountLabel(installation: GitHubAvailableInstallationApi): string {
    return installation.account_name ?? `installation ${installation.installation_id}`
}

export function GitHubInstallationLink({
    installations,
    loading,
    onLink,
    projectName,
}: {
    installations: GitHubAvailableInstallationApi[]
    loading: boolean
    onLink: (installationId?: string) => void
    /** Named on the button, so it's clear which project the install lands in. */
    projectName?: string
}): JSX.Element | null {
    if (installations.length === 0) {
        return null
    }

    if (installations.length === 1) {
        // Always name the installation, even when there's only one to pick. Omitting it asks the
        // backend to auto-resolve from a sibling project, which an orphan installation has none of.
        return (
            <LemonButton
                type="secondary"
                size="small"
                loading={loading}
                onClick={() => onLink(installations[0].installation_id)}
            >
                Connect to {projectName ?? 'this project'}
            </LemonButton>
        )
    }

    return (
        <LemonMenu
            items={installations.map((installation) => ({
                key: installation.installation_id,
                label: accountLabel(installation),
                disabledReason: loading ? 'Connecting an account' : undefined,
                onClick: () => onLink(installation.installation_id),
            }))}
        >
            <LemonButton type="secondary" size="small" loading={loading} sideIcon={<IconChevronDown />}>
                Choose an account
            </LemonButton>
        </LemonMenu>
    )
}
