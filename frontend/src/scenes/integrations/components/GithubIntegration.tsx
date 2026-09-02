import { useActions, useValues } from 'kea'

import { IconChevronDown, IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { GitHubInstallRequestsBanner } from 'lib/integrations/GitHubInstallRequestsBanner'
import { githubInstallRequestsLogic } from 'lib/integrations/githubInstallRequestsLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import type { IntegrationConnectSurface } from 'lib/integrations/utils'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { GitHubAvailableInstallationApi } from 'products/integrations/frontend/generated/api.schemas'

import { Integration, useIntegrations } from './Integration'

export function GithubIntegration({
    next,
    centered = false,
    connectSurface,
    connectText = 'Connect account',
    emphasizeConnect = false,
    showPersonalConnectionHelp = true,
}: {
    next?: string
    centered?: boolean
    connectText?: string
    emphasizeConnect?: boolean
    showPersonalConnectionHelp?: boolean
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
    const { hasPendingInstallRequests } = useValues(githubInstallRequestsLogic)
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
    const installRequestInProgress = hasPendingInstallRequests

    // Silent without `connectSurface`, because the only card rendered without one sits on the OAuth
    // landing page, which already reports every kind's connect click for itself.
    const reportConnect = (variant?: IntegrationConnectSurface): void => {
        if (connectSurface) {
            reportIntegrationConnectClicked('github', 'github', variant ?? connectSurface)
        }
    }

    return (
        <Integration kind="github" centered={centered}>
            {/* w-full because Integration drops its children into a bare flex row, which would
                otherwise size the banner to its longest word. */}
            <div className="flex flex-col gap-y-4 w-full">
                <GitHubInstallRequestsBanner
                    finishConnectingUrl={authorizationUrl}
                    onFinishConnecting={() => reportConnect('install_approved_banner')}
                    variant={emphasizeConnect ? 'onboarding' : 'default'}
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
                                emphasizeInstallation={emphasizeConnect}
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
                {installRequestInProgress ? null : emphasizeConnect && !isConnected ? (
                    <div className="flex w-full flex-col items-center gap-4">
                        <div className="flex flex-wrap justify-center gap-2">
                            <LemonButton
                                type={canLinkExisting ? 'secondary' : 'primary'}
                                icon={<IconGithub />}
                                disableClientSideRouting
                                to={authorizationUrl}
                                onClick={() => reportConnect()}
                            >
                                {canLinkExisting ? 'Connect a different organization or repository' : connectText}
                            </LemonButton>
                        </div>
                        <p className="m-0 max-w-[520px] text-center text-[13px] text-tertiary">
                            PostHog uses GitHub to create reports and pull requests based on your code. After connecting
                            GitHub, you can run Wizard in the background to complete setup.
                        </p>
                    </div>
                ) : (
                    <div className={cn('flex flex-wrap gap-2', centered && 'justify-center')}>
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
                            {isConnected ? 'Manage on GitHub' : connectText}
                        </LemonButton>
                    </div>
                )}
                {isConnected && (
                    <p className={cn('text-secondary text-xs mb-0', centered && 'text-center')}>
                        Add the PostHog app to another GitHub account, or change which repositories it can see.
                    </p>
                )}
                {showPersonalConnectionHelp &&
                    !isConnected &&
                    installations.length === 0 &&
                    githubPersonalConnected === false && (
                        <p className={cn('text-secondary text-xs mb-0', centered && 'text-center')}>
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
    emphasizeInstallation = false,
}: {
    installations: GitHubAvailableInstallationApi[]
    loading: boolean
    onLink: (installationId?: string) => void
    /** Named on the button, so it's clear which project the install lands in. */
    projectName?: string
    emphasizeInstallation?: boolean
}): JSX.Element | null {
    if (installations.length === 0) {
        return null
    }

    if (installations.length === 1) {
        // Always name the installation, even when there's only one to pick. Omitting it asks the
        // backend to auto-resolve from a sibling project, which an orphan installation has none of.
        return (
            <LemonButton
                type={emphasizeInstallation ? 'primary' : 'secondary'}
                size="small"
                loading={loading}
                onClick={() => onLink(installations[0].installation_id)}
            >
                {emphasizeInstallation
                    ? `Connect ${accountLabel(installations[0])}`
                    : `Connect to ${projectName ?? 'this project'}`}
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
            <LemonButton
                type={emphasizeInstallation ? 'primary' : 'secondary'}
                size="small"
                loading={loading}
                sideIcon={<IconChevronDown />}
            >
                {emphasizeInstallation ? 'Choose an existing installation' : 'Choose an account'}
            </LemonButton>
        </LemonMenu>
    )
}
