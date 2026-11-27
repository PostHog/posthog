import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconGithub, IconPlus, IconRefresh, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import { Badge, Button, Item, ItemActions, ItemContent, ItemDescription, Skeleton, Text } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { buildGithubDisconnectDescription } from 'lib/integrations/githubDisconnectCopy'
import { GitHubInstallRequestsBanner } from 'lib/integrations/GitHubInstallRequestsBanner'
import { GitHubRepoSummary } from 'lib/integrations/GitHubRepoSummary'
import { QuillIntegrationList } from 'lib/integrations/QuillIntegrationList'
import { QuillIntegrationRow } from 'lib/integrations/QuillIntegrationRow'
import { userGithubIntegrationLogic } from 'lib/integrations/userGithubIntegrationLogic'
import { IconSlack } from 'lib/lemon-ui/icons'

import {
    LinkableSlackWorkspace,
    personalIntegrationsLogic,
    PersonalGitHubIntegration,
    PersonalSlackIntegration,
} from './personalIntegrationsLogic'

// Personal integrations are a separate table with their own connect surface, so they get
// their own event: saved insights already count `integration_connect_clicked` unfiltered and
// would silently start including personal links.
function reportPersonalIntegrationConnectClicked(kind: string): void {
    posthog.capture('personal integration connect clicked', { integration_kind: kind })
}

function GitHubInstallationRow({ integration }: { integration: PersonalGitHubIntegration }): JSX.Element {
    const { disconnectGitHub, connectGitHub } = useActions(personalIntegrationsLogic)
    const { githubConnecting } = useValues(personalIntegrationsLogic)

    const installationId = integration.installation_id
    const accountType = integration.account?.type
    const accountName = integration.account?.name

    const repositorySelection = integration.repository_selection
    const logic = installationId ? userGithubIntegrationLogic({ installationId, repositorySelection }) : null
    const { repositories, repositoriesLoading, repositoriesTotal } = useValues(
        logic ?? userGithubIntegrationLogic({ installationId: '' })
    )
    const installationUnavailable = integration.installation_status === 'unavailable'
    const needsReauthorization = !!integration.needs_reauthorization
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleDisconnect = (): void => {
        LemonDialog.open({
            title: `Disconnect ${accountName || 'GitHub installation'}?`,
            description: (
                <>
                    <LemonBanner type="warning" className="my-4 text-balance">
                        Any PostHog Desktop agent runs <em>currently in progress</em> will be unable to push commits or
                        open pull requests on GitHub.
                    </LemonBanner>
                    <p>
                        {buildGithubDisconnectDescription(
                            accountName || 'this account',
                            !!integration.installation_shared,
                            'account'
                        )}
                    </p>
                </>
            ),
            primaryButton: {
                children: 'Disconnect',
                status: 'danger',
                onClick: () => installationId && disconnectGitHub(installationId),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    const handleReconnect = (): void => {
        reportPersonalIntegrationConnectClicked('github')
        connectGitHub()
    }

    const reconnectDisabledReason = githubConnecting ? 'Starting GitHub authorization…' : undefined

    const repoSummary = (
        <GitHubRepoSummary
            repoNames={repositories.map((r: { name: string }) => r.name)}
            loading={repositoriesLoading}
            installationId={installationId}
            accountType={accountType}
            accountName={accountName}
            repositorySelection={repositorySelection}
            total={repositoriesTotal}
        />
    )

    if (todayRailNav) {
        return (
            <QuillIntegrationRow
                icon={<IconGithub />}
                title={accountName || 'GitHub'}
                badges={
                    <>
                        <Badge>{accountType === 'Organization' ? 'Org' : 'Personal'}</Badge>
                        {needsReauthorization ? <Badge variant="warning">Needs reconnecting</Badge> : null}
                    </>
                }
                meta={
                    <>
                        {integration.created_at ? (
                            <span>
                                Connected <TZLabel time={integration.created_at} className="align-baseline" />
                            </span>
                        ) : (
                            <span>Connected</span>
                        )}
                        {integration.uses_shared_installation ? <span> · Also used by this project</span> : null}
                    </>
                }
                action={
                    <Button
                        variant="destructive-outline"
                        size="icon"
                        aria-label="Disconnect this installation"
                        tooltip="Disconnect this installation"
                        onClick={handleDisconnect}
                    >
                        <IconTrash />
                    </Button>
                }
            >
                {repoSummary}
                {installationUnavailable ? (
                    <Item tone="destructive" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                The PostHog app was removed from GitHub. Disconnect this installation, then connect
                                again if you still need it.
                            </ItemDescription>
                        </ItemContent>
                    </Item>
                ) : null}
                {needsReauthorization ? (
                    <Item tone="warning" size="sm">
                        <ItemContent>
                            <ItemDescription>
                                GitHub stopped accepting this connection
                                {integration.needs_reauthorization_at ? (
                                    <>
                                        {' '}
                                        <TZLabel
                                            time={integration.needs_reauthorization_at}
                                            className="align-baseline"
                                        />
                                    </>
                                ) : null}
                                . Reconnect to let PostHog read your repos and open pull requests as you again.
                            </ItemDescription>
                        </ItemContent>
                        <ItemActions>
                            <Button
                                variant="outline"
                                onClick={handleReconnect}
                                loading={githubConnecting}
                                disabledReason={reconnectDisabledReason}
                            >
                                <IconRefresh />
                                Reconnect
                            </Button>
                        </ItemActions>
                    </Item>
                ) : null}
            </QuillIntegrationRow>
        )
    }

    return (
        <div className="flex items-center gap-4 px-4 py-3">
            <div className="shrink-0">
                <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-surface-secondary text-2xl">
                    <IconGithub />
                </div>
            </div>
            <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{accountName || 'GitHub'}</span>
                    {accountType === 'Organization' ? (
                        <span className="text-xs text-muted bg-surface-secondary px-1.5 py-0.5 rounded">Org</span>
                    ) : (
                        <span className="text-xs text-muted bg-surface-secondary px-1.5 py-0.5 rounded">Personal</span>
                    )}
                    {needsReauthorization ? (
                        <LemonTag type="warning" size="small">
                            Needs reconnecting
                        </LemonTag>
                    ) : null}
                </div>
                <div className="mt-0.5 text-xs text-secondary">
                    {integration.created_at ? (
                        <>
                            Connected <TZLabel time={integration.created_at} className="align-baseline" />
                        </>
                    ) : (
                        'Connected'
                    )}
                    {integration.uses_shared_installation ? ' · Also used by this project' : ''}
                </div>
                <div className="mt-1">{repoSummary}</div>
                {installationUnavailable ? (
                    <LemonBanner type="error" className="mt-2">
                        The PostHog app was removed from GitHub. Disconnect this installation, then connect again if you
                        still need it.
                    </LemonBanner>
                ) : null}
                {needsReauthorization ? (
                    <LemonBanner
                        type="warning"
                        className="mt-2"
                        alignItems="start"
                        action={{
                            children: 'Reconnect',
                            icon: <IconRefresh />,
                            onClick: handleReconnect,
                            loading: githubConnecting,
                            disabledReason: reconnectDisabledReason,
                        }}
                    >
                        GitHub stopped accepting this connection
                        {integration.needs_reauthorization_at ? (
                            <>
                                {' '}
                                <TZLabel time={integration.needs_reauthorization_at} className="align-baseline" />
                            </>
                        ) : null}
                        . Reconnect to let PostHog read your repos and open pull requests as you again.
                    </LemonBanner>
                ) : null}
            </div>
            <div className="flex shrink-0 items-center">
                <LemonButton
                    size="small"
                    type="secondary"
                    status="danger"
                    icon={<IconTrash />}
                    onClick={handleDisconnect}
                    tooltip="Disconnect this installation"
                />
            </div>
        </div>
    )
}

function SlackLinkRow({ integration }: { integration: PersonalSlackIntegration }): JSX.Element {
    const { disconnectSlack } = useActions(personalIntegrationsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleUnlink = (): void => {
        LemonDialog.open({
            title: `Unlink ${integration.slack_team_name || 'this Slack workspace'}?`,
            description: (
                <p>
                    PostHog will go back to matching you by email. If your Slack email doesn't match any PostHog account
                    in the organization, mentions won't route to you until you link again. PostHog tasks also lose the
                    Slack access that came with this link.
                </p>
            ),
            primaryButton: {
                children: 'Unlink',
                status: 'danger',
                onClick: () => disconnectSlack(integration.slack_user_id),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    if (todayRailNav) {
        return (
            <QuillIntegrationRow
                icon={<IconSlack />}
                title={integration.slack_team_name || 'Slack workspace'}
                badges={<Badge className="font-mono">{integration.slack_user_id}</Badge>}
                meta={
                    <>
                        {integration.created_at ? (
                            <span>
                                Linked <TZLabel time={integration.created_at} className="align-baseline" />
                            </span>
                        ) : (
                            <span>Linked</span>
                        )}
                        {integration.slack_email_at_link ? (
                            <span>{` · ${integration.slack_email_at_link}`}</span>
                        ) : null}
                    </>
                }
                action={
                    <Button
                        variant="destructive-outline"
                        size="icon"
                        aria-label="Unlink this Slack account"
                        tooltip="Unlink this Slack account"
                        onClick={handleUnlink}
                    >
                        <IconTrash />
                    </Button>
                }
            />
        )
    }

    return (
        <div className="flex items-center gap-4 px-4 py-3">
            <div className="shrink-0">
                <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-surface-secondary text-2xl">
                    <IconSlack />
                </div>
            </div>
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">{integration.slack_team_name || 'Slack workspace'}</span>
                    <span className="text-xs text-muted bg-surface-secondary px-1.5 py-0.5 rounded font-mono">
                        {integration.slack_user_id}
                    </span>
                </div>
                <div className="mt-0.5 text-xs text-secondary">
                    {integration.created_at ? (
                        <>
                            Linked <TZLabel time={integration.created_at} className="align-baseline" />
                        </>
                    ) : (
                        'Linked'
                    )}
                    {integration.slack_email_at_link ? ` · ${integration.slack_email_at_link}` : ''}
                </div>
            </div>
            <div className="flex shrink-0 items-center">
                <LemonButton
                    size="small"
                    type="secondary"
                    status="danger"
                    icon={<IconTrash />}
                    onClick={handleUnlink}
                    tooltip="Unlink this Slack account"
                />
            </div>
        </div>
    )
}

export function PersonalGitHubIntegrations(): JSX.Element {
    const { integrations, healthyIntegrations, integrationsLoading, githubConnecting } =
        useValues(personalIntegrationsLogic)
    const { connectGitHub, startPolling, stopPolling } = useActions(personalIntegrationsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    // Refresh the personal rows while this section stays mounted, so an App removed on GitHub shows
    // its unavailable notice without a manual reload.
    useOnMountEffect(() => {
        startPolling()
        return () => stopPolling()
    })

    const handleConnect = (): void => {
        reportPersonalIntegrationConnectClicked('github')
        connectGitHub()
    }

    const connectDisabledReason = githubConnecting ? 'Starting GitHub installation…' : undefined

    if (integrationsLoading && integrations.length === 0) {
        if (todayRailNav) {
            return <Skeleton className="h-16 w-full" />
        }

        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton className="h-16 w-full" />
            </div>
        )
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-2">
                <GitHubInstallRequestsBanner onFinishConnecting={handleConnect} />
                <QuillIntegrationList
                    isEmpty={integrations.length === 0}
                    emptyIcon={<IconGithub />}
                    emptyTitle="No GitHub installations connected yet"
                    emptyDescription="Connect to let PostHog access your repos, attribute commits, open pull requests, and assign issues as you. You can add multiple installations for different accounts or organizations."
                    footer={
                        <>
                            <Button
                                variant="outline"
                                onClick={handleConnect}
                                loading={githubConnecting}
                                disabledReason={connectDisabledReason}
                            >
                                <IconPlus />
                                {healthyIntegrations.length === 0 ? 'Connect GitHub' : 'Add account/organization'}
                            </Button>
                            <Text size="xs" variant="muted" render={<span className="m-0 text-balance" />}>
                                Heads up: if GitHub's <strong>Save</strong> button is disabled at the end of the flow,
                                flip between <strong>All repositories</strong> and{' '}
                                <strong>Only select repositories</strong> to proceed.
                            </Text>
                        </>
                    }
                >
                    {integrations.map((integration: PersonalGitHubIntegration) => (
                        <GitHubInstallationRow key={integration.installation_id} integration={integration} />
                    ))}
                </QuillIntegrationList>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <GitHubInstallRequestsBanner onFinishConnecting={handleConnect} />
            <div className="divide-y rounded border bg-surface-primary">
                {integrations.length === 0 ? (
                    <div className="px-4 py-6 text-center text-sm text-secondary">
                        <IconGithub className="text-3xl mb-2 opacity-40" />
                        <p className="mb-1">No GitHub installations connected yet</p>
                        <p className="text-xs text-muted text-balance">
                            Connect to let PostHog access your repos, attribute commits, open pull requests, and assign
                            issues as you. You can add multiple installations for different accounts or organizations.
                        </p>
                    </div>
                ) : (
                    integrations.map((integration: PersonalGitHubIntegration) => (
                        <GitHubInstallationRow key={integration.installation_id} integration={integration} />
                    ))
                )}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={handleConnect}
                        loading={githubConnecting}
                        disabledReason={connectDisabledReason}
                    >
                        {healthyIntegrations.length === 0 ? 'Connect GitHub' : 'Add account/organization'}
                    </LemonButton>
                    <span className="text-xs text-secondary text-balance">
                        Heads up: if GitHub's <strong>Save</strong> button is disabled at the end of the flow, flip
                        between <strong>All repositories</strong> and <strong>Only select repositories</strong> to
                        proceed.
                    </span>
                </div>
            </div>
        </div>
    )
}

function openSlackWorkspacePicker(
    workspaces: LinkableSlackWorkspace[],
    connectSlack: (payload: { workspace: LinkableSlackWorkspace }) => void
): void {
    LemonDialog.open({
        title: 'Pick a Slack workspace to link',
        description: (
            <div className="deprecated-space-y-2">
                <p className="text-sm text-secondary">
                    Your organizations are connected to multiple Slack workspaces. Pick the one you want to bind your
                    PostHog identity to.
                </p>
                <div className="divide-y rounded border">
                    {workspaces.map((workspace) => (
                        <LemonButton
                            key={`${workspace.posthog_team_id}:${workspace.slack_team_id}`}
                            fullWidth
                            type="tertiary"
                            icon={<IconSlack />}
                            sideIcon={<IconPlus />}
                            onClick={() => connectSlack({ workspace })}
                        >
                            <div className="flex flex-col min-w-0">
                                <span className="font-semibold truncate">
                                    {workspace.slack_team_name || workspace.slack_team_id}
                                </span>
                                <span className="text-xs text-secondary truncate">
                                    {workspace.posthog_organization_name} · {workspace.posthog_team_name}
                                </span>
                            </div>
                        </LemonButton>
                    ))}
                </div>
            </div>
        ),
        primaryButton: null,
        secondaryButton: { children: 'Cancel' },
    })
}

export function PersonalSlackIntegrations(): JSX.Element {
    const {
        slackIntegrations,
        slackIntegrationsLoading,
        slackConnectLoading,
        linkableSlackWorkspaces,
        linkableSlackWorkspacesLoading,
    } = useValues(personalIntegrationsLogic)
    const { connectSlack } = useActions(personalIntegrationsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const hasLinkableWorkspaces = linkableSlackWorkspaces.length > 0
    const onConnect = (): void => {
        if (linkableSlackWorkspaces.length > 1) {
            openSlackWorkspacePicker(linkableSlackWorkspaces, connectSlack)
        } else if (linkableSlackWorkspaces.length === 1) {
            connectSlack({ workspace: linkableSlackWorkspaces[0] })
        }
    }

    const connectDisabledReason = !hasLinkableWorkspaces ? 'Loading…' : undefined

    if (todayRailNav) {
        if (slackIntegrationsLoading && slackIntegrations.length === 0) {
            return <Skeleton className="h-16 w-full" />
        }

        return (
            <QuillIntegrationList
                isEmpty={slackIntegrations.length === 0}
                emptyIcon={<IconSlack />}
                emptyTitle="No Slack account linked"
                emptyDescription="Link your Slack identity so @PostHog mentions route to you even when your Slack email and PostHog email don't match."
                footer={
                    linkableSlackWorkspacesLoading || hasLinkableWorkspaces ? (
                        <>
                            <Button
                                variant="outline"
                                onClick={onConnect}
                                loading={slackConnectLoading || linkableSlackWorkspacesLoading}
                                disabledReason={connectDisabledReason}
                            >
                                <IconPlus />
                                {slackIntegrations.length === 0 ? 'Link my Slack account' : 'Link another workspace'}
                            </Button>
                            <Text size="xs" variant="muted" render={<span className="m-0 text-balance" />}>
                                You'll be redirected to Slack to authorize this PostHog account. The link binds your
                                Slack user id to your PostHog account — no Slack token is kept after the redirect.
                            </Text>
                        </>
                    ) : null
                }
            >
                {slackIntegrations.map((integration: PersonalSlackIntegration) => (
                    <SlackLinkRow key={integration.id} integration={integration} />
                ))}
            </QuillIntegrationList>
        )
    }

    return (
        <div className="divide-y rounded border bg-surface-primary">
            {slackIntegrationsLoading && slackIntegrations.length === 0 ? (
                <LemonSkeleton className="h-16 w-full" />
            ) : slackIntegrations.length === 0 ? (
                <div className="px-4 py-6 text-center text-sm text-secondary">
                    <IconSlack className="text-3xl mb-2 opacity-40" />
                    <p className="mb-1">No Slack account linked</p>
                    <p className="text-xs text-muted text-balance">
                        Link your Slack identity so @PostHog mentions route to you even when your Slack email and
                        PostHog email don't match.
                    </p>
                </div>
            ) : (
                slackIntegrations.map((integration: PersonalSlackIntegration) => (
                    <SlackLinkRow key={integration.id} integration={integration} />
                ))
            )}
            {/* Button is hidden when there are no linkable workspaces left — every workspace
                accessible via the user's orgs has already been linked, or none are connected at
                all. Server still defends with a 400 if the user gets here some other way. */}
            {(linkableSlackWorkspacesLoading || hasLinkableWorkspaces) && (
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlus />}
                        onClick={onConnect}
                        loading={slackConnectLoading || linkableSlackWorkspacesLoading}
                        disabledReason={connectDisabledReason}
                    >
                        {slackIntegrations.length === 0 ? 'Link my Slack account' : 'Link another workspace'}
                    </LemonButton>
                    <span className="text-xs text-secondary text-balance">
                        You'll be redirected to Slack to authorize this PostHog account. The link binds your Slack user
                        id to your PostHog account — no Slack token is kept after the redirect.
                    </span>
                </div>
            )}
        </div>
    )
}
