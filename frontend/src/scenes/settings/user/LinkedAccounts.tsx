import { useActions, useValues } from 'kea'

import { IconGear, IconGithub } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { IconBranch } from 'lib/lemon-ui/icons'
import { humanFriendlyDetailedTime } from 'lib/utils'

import { linkedAccountsLogic } from './linkedAccountsLogic'

export function LinkedAccounts(): JSX.Element {
    const {
        linkedAccounts,
        linkedAccountsLoading,
        teamGitHubIntegrations,
        githubRepositories,
        githubRepositoriesLoading,
    } = useValues(linkedAccountsLogic)
    const { disconnectGitHub, connectGitHub } = useActions(linkedAccountsLogic)

    const github = linkedAccounts.find((a) => a.kind === 'github')
    const hasTeamIntegration = teamGitHubIntegrations.length > 0
    const teamAccountNames = teamGitHubIntegrations
        .map((ti) => ti.account_name)
        .filter(Boolean)
        .join(', ')

    const handleDisconnect = (): void => {
        LemonDialog.open({
            title: 'Disconnect GitHub?',
            description:
                'PostHog will no longer be able to attribute code changes to your account or open pull requests on your behalf. You can reconnect anytime.',
            primaryButton: {
                children: 'Disconnect',
                status: 'danger',
                onClick: () => disconnectGitHub(),
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    if (linkedAccountsLoading && linkedAccounts.length === 0) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton className="h-16 w-full" />
            </div>
        )
    }

    const installationId = github?.installation_id
    const accountType = github?.account?.type
    const accountName = github?.account?.name
    const manageUrl =
        accountType === 'Organization' && accountName
            ? `https://github.com/organizations/${accountName}/settings/installations/${installationId}`
            : `https://github.com/settings/installations/${installationId}`

    return (
        <div className="deprecated-space-y-3">
            <div className="divide-y rounded border bg-surface-primary">
                <div className="flex items-center gap-4 px-4 py-3">
                    <div className={`shrink-0${github?.connected ? '' : ' opacity-60'}`}>
                        <div className="flex h-10 w-10 items-center justify-center rounded-md border bg-surface-secondary text-2xl">
                            <IconGithub />
                        </div>
                    </div>
                    <div className={`min-w-0 flex-1${github?.connected ? '' : ' opacity-60'}`}>
                        <div className="flex items-center gap-2">
                            <span className="font-semibold">GitHub</span>
                            {github?.connected && github.account_identifier ? (
                                <span className="truncate text-sm text-secondary">· {github.account_identifier}</span>
                            ) : null}
                        </div>
                        <div className="mt-0.5 text-xs text-secondary">
                            {!github?.connected ? (
                                'Not connected'
                            ) : (
                                <>
                                    {github.created_at
                                        ? `Connected ${humanFriendlyDetailedTime(github.created_at)}`
                                        : 'Connected'}
                                    {github.uses_shared_installation && github.account
                                        ? ` · Using project's ${github.account.name} installation`
                                        : github.account
                                          ? ` · Own installation on ${github.account.name}`
                                          : null}
                                </>
                            )}
                        </div>
                        {github?.connected ? (
                            githubRepositoriesLoading && githubRepositories.length === 0 ? (
                                <div className="flex items-center gap-1 text-xs text-muted mt-1 min-h-5">
                                    <Spinner className="text-sm" />
                                    Loading repositories...
                                </div>
                            ) : githubRepositories.length > 0 ? (
                                <div className="flex items-center gap-2 mt-1 min-h-5">
                                    <div className="text-xs text-muted">
                                        <IconBranch className="inline mr-1 text-sm" />
                                        {githubRepositories.length} repositor
                                        {githubRepositories.length === 1 ? 'y' : 'ies'} accessible:{' '}
                                        {githubRepositories.length <= 3
                                            ? githubRepositories.join(', ')
                                            : `${githubRepositories.slice(0, 3).join(', ')} and ${githubRepositories.length - 3} more`}
                                    </div>
                                    {installationId ? (
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            icon={<IconGear />}
                                            onClick={() => window.open(manageUrl, '_blank')}
                                            tooltip="Manage repository access on GitHub"
                                        />
                                    ) : null}
                                </div>
                            ) : (
                                <div className="flex items-center gap-2 mt-1 min-h-5">
                                    <div className="text-xs text-muted">
                                        <IconBranch className="inline mr-1 text-sm" />
                                        No repositories accessible
                                    </div>
                                    {installationId ? (
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            icon={<IconGear />}
                                            onClick={() => window.open(manageUrl, '_blank')}
                                            tooltip="Configure repository access"
                                        />
                                    ) : null}
                                </div>
                            )
                        ) : (
                            <div className="mt-1 text-xs text-secondary italic text-balance">
                                {hasTeamIntegration ? (
                                    <>
                                        Your project is already connected to <b>{teamAccountNames}</b> on GitHub.
                                        Connect your account to let PostHog attribute commits, open pull requests, and
                                        assign issues as you. GitHub will ask you to authorize the existing installation
                                        — this won't change the project's repo access.
                                    </>
                                ) : (
                                    'Connect to let PostHog access your repos, attribute commits, open pull requests, and assign issues as you.'
                                )}
                            </div>
                        )}
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                        {!github?.connected ? (
                            <LemonButton type="primary" size="small" onClick={connectGitHub}>
                                Connect
                            </LemonButton>
                        ) : (
                            <LemonButton type="tertiary" status="danger" size="small" onClick={handleDisconnect}>
                                Disconnect
                            </LemonButton>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
