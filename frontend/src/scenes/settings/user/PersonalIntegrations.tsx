import { useActions, useValues } from 'kea'

import { IconGithub, IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { GitHubRepoSummary } from 'lib/integrations/GitHubRepoSummary'
import { userGithubIntegrationLogic } from 'lib/integrations/userGithubIntegrationLogic'
import { IconSlack } from 'lib/lemon-ui/icons'

import {
    LinkableSlackWorkspace,
    personalIntegrationsLogic,
    PersonalGitHubIntegration,
    PersonalSlackIntegration,
} from './personalIntegrationsLogic'

function GitHubInstallationRow({ integration }: { integration: PersonalGitHubIntegration }): JSX.Element {
    const { disconnectGitHub } = useActions(personalIntegrationsLogic)

    const installationId = integration.installation_id
    const accountType = integration.account?.type
    const accountName = integration.account?.name

    const logic = installationId ? userGithubIntegrationLogic({ installationId }) : null
    const { repositories, repositoriesLoading } = useValues(logic ?? userGithubIntegrationLogic({ installationId: '' }))

    const handleDisconnect = (): void => {
        LemonDialog.open({
            title: `Disconnect ${accountName || 'GitHub installation'}?`,
            description: (
                <>
                    <LemonBanner type="warning" className="my-4 text-balance">
                        Any PostHog Code agent runs <em>currently in progress</em> will be unable to push commits or
                        open pull requests on GitHub.
                    </LemonBanner>
                    <p>
                        PostHog will no longer be able to access repos from this installation or act on your behalf
                        there.
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

    return (
        <div className="flex items-center gap-4 px-4 py-3">
            <div className="shrink-0">
                <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-surface-secondary text-2xl">
                    <IconGithub />
                </div>
            </div>
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">{accountName || 'GitHub'}</span>
                    {accountType === 'Organization' ? (
                        <span className="text-xs text-muted bg-surface-secondary px-1.5 py-0.5 rounded">Org</span>
                    ) : (
                        <span className="text-xs text-muted bg-surface-secondary px-1.5 py-0.5 rounded">Personal</span>
                    )}
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
                <div className="mt-1">
                    <GitHubRepoSummary
                        repoNames={repositories.map((r: { name: string }) => r.name)}
                        loading={repositoriesLoading}
                        installationId={installationId}
                        accountType={accountType}
                        accountName={accountName}
                    />
                </div>
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

    const handleUnlink = (): void => {
        LemonDialog.open({
            title: `Unlink ${integration.slack_team_name || 'this Slack workspace'}?`,
            description: (
                <p>
                    PostHog will go back to matching you by email. If your Slack email doesn't match any PostHog account
                    in the organization, mentions won't route to you until you link again.
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
    const { integrations, integrationsLoading, githubConnecting } = useValues(personalIntegrationsLogic)
    const { connectGitHub } = useActions(personalIntegrationsLogic)

    if (integrationsLoading && integrations.length === 0) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton className="h-16 w-full" />
            </div>
        )
    }

    return (
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
                    onClick={connectGitHub}
                    loading={githubConnecting}
                    disabledReason={githubConnecting ? 'Starting GitHub installation…' : undefined}
                >
                    {integrations.length === 0 ? 'Connect GitHub' : 'Add account/organization'}
                </LemonButton>
                <span className="text-xs text-secondary text-balance">
                    Heads up: if GitHub's <strong>Save</strong> button is disabled at the end of the flow, flip between{' '}
                    <strong>All repositories</strong> and <strong>Only select repositories</strong> to proceed.
                </span>
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

    const hasLinkableWorkspaces = linkableSlackWorkspaces.length > 0
    const onConnect = (): void => {
        if (linkableSlackWorkspaces.length > 1) {
            openSlackWorkspacePicker(linkableSlackWorkspaces, connectSlack)
        } else if (linkableSlackWorkspaces.length === 1) {
            connectSlack({ workspace: linkableSlackWorkspaces[0] })
        }
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
                        disabledReason={!hasLinkableWorkspaces ? 'Loading…' : undefined}
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
