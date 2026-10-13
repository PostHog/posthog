import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronDown, IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { GitHubInstallRequestsBanner } from 'lib/integrations/GitHubInstallRequestsBanner'
import { githubInstallRequestsLogic } from 'lib/integrations/githubInstallRequestsLogic'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import type { IntegrationConnectSurface, IntegrationLinkExistingCounts } from 'lib/integrations/utils'
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
    const [visibleDiscoveryId, setVisibleDiscoveryId] = useState<string | null>(null)
    const { currentTeam } = useValues(teamLogic)
    const {
        linkedGithubInstallationLoading,
        githubAvailableInstallations,
        githubPersonalConnected,
        githubAvailableInstallationsResponse,
        githubAvailableInstallationsResponseLoading,
        githubDiscoveryFailed,
    } = useValues(integrationsLogic)
    const {
        linkExistingGithubInstallation,
        loadGithubAvailableInstallations,
        startPolling,
        stopPolling,
        subscribeGithubSuggestions,
        unsubscribeGithubSuggestions,
    } = useActions(integrationsLogic)
    const { reportIntegrationConnectClicked, reportIntegrationLinkExistingOffered, reportGithubInstallationSelected } =
        useActions(eventUsageLogic)
    const { hasPendingInstallRequests } = useValues(githubInstallRequestsLogic)
    const githubIntegrations = useIntegrations('github')

    // integrationsLogic is a singleton mounted from dozens of unrelated surfaces, so this fetch
    // hangs off the GitHub setup UI instead of the shared integrations load. Polling is likewise
    // scoped to the settings surface: an uninstall on GitHub should show up while someone is looking.
    useOnMountEffect(() => {
        startPolling()
        subscribeGithubSuggestions()
        return () => {
            unsubscribeGithubSuggestions()
            stopPolling()
        }
    })

    const settingsPath = next ?? urls.settings('environment-integrations')
    const authorizationUrl = api.integrations.authorizeUrl({
        next: currentTeam?.id ? urls.project(currentTeam.id, settingsPath) : settingsPath,
        kind: 'github',
    })

    const installations = githubAvailableInstallations ?? []
    const isConnected = githubIntegrations.length > 0
    const canLinkExisting = !isConnected && !githubAvailableInstallationsResponseLoading && installations.length > 0
    const multipleInstallations = installations.length > 1
    const pickerOpen =
        visibleDiscoveryId !== null && visibleDiscoveryId === githubAvailableInstallationsResponse?.discovery_id
    const installRequestInProgress = hasPendingInstallRequests

    // A discovery response is reported only after its suggestions render.
    const offeredInstallationIds =
        canLinkExisting && (!multipleInstallations || pickerOpen)
            ? installations.map((installation) => installation.installation_id).join(',')
            : ''
    useEffect(() => {
        if (offeredInstallationIds) {
            reportIntegrationLinkExistingOffered('github', connectSurface ?? 'integration_landing_page', {
                ...countInstallations(installations),
                discoveryId: githubAvailableInstallationsResponse?.discovery_id,
                installationIds: installations.map((installation) => installation.installation_id),
                responseAgeMs: Math.max(
                    0,
                    Date.now() - Date.parse(githubAvailableInstallationsResponse?.discovered_at ?? '')
                ),
            })
        }
    }, [offeredInstallationIds, connectSurface, githubAvailableInstallationsResponse?.discovery_id]) // oxlint-disable-line react-hooks/exhaustive-deps

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
                        {/* Wraps because the centered cards (onboarding, the integration landing page)
                            are narrow enough that the sentence and the button can't share a row. */}
                        <div className="flex flex-wrap items-center gap-3">
                            <span className="min-w-0 text-sm font-normal">
                                {multipleInstallations ? (
                                    <>PostHog is already installed on more than one GitHub account.</>
                                ) : (
                                    <>
                                        {installations[0].source_team_id !== null ? (
                                            <span>
                                                PostHog is installed on{' '}
                                                <strong>{accountLabel(installations[0])}</strong> and connected to{' '}
                                                <strong>
                                                    {installations[0].source_team_name ??
                                                        `project ${installations[0].source_team_id}`}
                                                </strong>
                                                .
                                            </span>
                                        ) : (
                                            <span>
                                                PostHog is installed on the GitHub account{' '}
                                                <strong>{accountLabel(installations[0])}</strong>.{' '}
                                                <span>
                                                    {sourceLabel(
                                                        installations[0],
                                                        githubAvailableInstallationsResponse?.personal_github_login
                                                    )}
                                                    .
                                                </span>
                                            </span>
                                        )}
                                    </>
                                )}
                            </span>
                            <GitHubInstallationLink
                                onVisibilityChange={(visible) =>
                                    setVisibleDiscoveryId(
                                        visible ? (githubAvailableInstallationsResponse?.discovery_id ?? null) : null
                                    )
                                }
                                personalGithubLogin={githubAvailableInstallationsResponse?.personal_github_login}
                                installations={installations}
                                loading={linkedGithubInstallationLoading}
                                emphasizeInstallation={emphasizeConnect}
                                onLink={(installationId) => {
                                    // Reusing an existing install never leaves PostHog, so it's a
                                    // connect that skips GitHub entirely — worth separating from the
                                    // clicks that redirect out. Falls back to `connectSurface` like
                                    // every other button here, instead of a fixed literal, so the
                                    // surface still says where the click happened.
                                    reportConnect(connectSurface === 'settings' ? 'settings_link_existing' : undefined)
                                    reportGithubInstallationSelected(
                                        connectSurface ?? 'integration_landing_page',
                                        githubAvailableInstallationsResponse?.discovery_id,
                                        installationId,
                                        Math.max(
                                            0,
                                            Date.now() -
                                                Date.parse(githubAvailableInstallationsResponse?.discovered_at ?? '')
                                        )
                                    )
                                    linkExistingGithubInstallation(installationId)
                                }}
                                projectName={currentTeam?.name}
                            />
                        </div>
                        {installations.some((installation) => installation.source_team_id === null) && (
                            <p className="mb-0 mt-2 text-sm font-normal">
                                GitHub can include accounts whose repositories you can access.
                            </p>
                        )}
                    </LemonBanner>
                )}
                {!isConnected && githubAvailableInstallationsResponseLoading && (
                    <p className="text-secondary mb-0">Looking for existing GitHub installations…</p>
                )}
                {!isConnected &&
                    !githubAvailableInstallationsResponseLoading &&
                    (githubDiscoveryFailed ||
                        githubAvailableInstallationsResponse?.personal_discovery_status === 'unavailable') && (
                        <LemonBanner type="warning">
                            <div className="flex flex-wrap items-center gap-2">
                                <span>Couldn't check your personal GitHub connection.</span>
                                <LemonButton size="small" onClick={loadGithubAvailableInstallations}>
                                    Retry
                                </LemonButton>
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
    return installation.account_name || `installation ${installation.installation_id}`
}

function countInstallations(installations: GitHubAvailableInstallationApi[]): IntegrationLinkExistingCounts {
    return {
        total: installations.length,
        sibling: installations.filter((installation) => installation.source_team_id !== null).length,
        orphan: installations.filter((installation) => installation.source_team_id === null).length,
        unnamed: installations.filter((installation) => !installation.account_name).length,
    }
}

// Where an entry came from decides whether an unfamiliar account reads as a teammate's work or as a
// stranger in your settings, so every entry says its source.
function sourceLabel(installation: GitHubAvailableInstallationApi, personalGithubLogin?: string | null): string {
    return installation.source_team_id !== null
        ? `Connected to ${installation.source_team_name ?? `project ${installation.source_team_id}`}`
        : `Found through your GitHub connection${personalGithubLogin ? ` as ${personalGithubLogin}` : ''}`
}

export function GitHubInstallationLink({
    installations,
    loading,
    onLink,
    projectName,
    emphasizeInstallation = false,
    personalGithubLogin,
    onVisibilityChange,
}: {
    installations: GitHubAvailableInstallationApi[]
    personalGithubLogin?: string | null
    onVisibilityChange?: (visible: boolean) => void
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
            onVisibilityChange={onVisibilityChange}
            items={installations.map((installation) => ({
                key: installation.installation_id,
                label: (
                    <span className="flex flex-col items-start">
                        <span>{accountLabel(installation)}</span>
                        <span className="text-xs text-secondary">{sourceLabel(installation, personalGithubLogin)}</span>
                    </span>
                ),
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
