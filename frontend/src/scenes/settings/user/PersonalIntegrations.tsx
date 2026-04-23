import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconGear, IconGithub, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { userGithubIntegrationLogic } from 'lib/integrations/userGithubIntegrationLogic'
import { IconBranch } from 'lib/lemon-ui/icons'

import { personalIntegrationsLogic, PersonalGitHubIntegration } from './personalIntegrationsLogic'

function GitHubRepositoryInfo({ installationId }: { installationId: string }): JSX.Element {
    const logic = userGithubIntegrationLogic({ installationId })
    const { repositories, repositoriesLoading } = useValues(logic)
    const { loadRepositories } = useActions(logic)

    useEffect(() => {
        loadRepositories()
    }, [loadRepositories])

    if (repositoriesLoading && repositories.length === 0) {
        return (
            <div className="flex items-center gap-1 text-xs text-muted mt-1 min-h-5">
                <Spinner className="text-sm" />
                Loading repositories...
            </div>
        )
    }

    if (repositories.length > 0) {
        return (
            <div className="text-xs text-muted mt-1 min-h-5">
                <IconBranch className="inline mr-1 text-sm" />
                {repositories.length} repositor
                {repositories.length === 1 ? 'y' : 'ies'} accessible:{' '}
                {repositories.length <= 3
                    ? repositories.map((r) => r.name).join(', ')
                    : `${repositories
                          .slice(0, 3)
                          .map((r) => r.name)
                          .join(', ')} and ${repositories.length - 3} more`}
            </div>
        )
    }

    return (
        <div className="text-xs text-muted mt-1 min-h-5">
            <IconBranch className="inline mr-1 text-sm" />
            No repositories accessible
        </div>
    )
}

function GitHubInstallationRow({ integration }: { integration: PersonalGitHubIntegration }): JSX.Element {
    const { disconnectGitHub } = useActions(personalIntegrationsLogic)

    const installationId = integration.installation_id
    const accountType = integration.account?.type
    const accountName = integration.account?.name
    const manageUrl =
        accountType === 'Organization' && accountName
            ? `https://github.com/organizations/${accountName}/settings/installations/${installationId}`
            : `https://github.com/settings/installations/${installationId}`

    const handleDisconnect = (): void => {
        LemonDialog.open({
            title: `Disconnect ${accountName || 'GitHub installation'}?`,
            description:
                'PostHog will no longer be able to access repos from this installation or act on your behalf there.',
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
                {installationId ? <GitHubRepositoryInfo installationId={installationId} /> : null}
            </div>
            <div className="flex shrink-0 items-center gap-2">
                {installationId ? (
                    <LemonButton
                        size="small"
                        type="secondary"
                        icon={<IconGear />}
                        onClick={() => window.open(manageUrl, '_blank')}
                        tooltip="Manage repository access on GitHub"
                    />
                ) : null}
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

export function PersonalIntegrations(): JSX.Element {
    const { githubIntegrations, githubIntegrationsLoading } = useValues(personalIntegrationsLogic)
    const { connectGitHub } = useActions(personalIntegrationsLogic)

    if (githubIntegrationsLoading && githubIntegrations.length === 0) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton className="h-16 w-full" />
            </div>
        )
    }

    return (
        <div className="deprecated-space-y-3">
            <div className="divide-y rounded border bg-surface-primary">
                {githubIntegrations.length === 0 ? (
                    <div className="px-4 py-6 text-center text-sm text-secondary">
                        <IconGithub className="text-3xl mb-2 opacity-40" />
                        <p className="mb-1">No GitHub installations connected yet</p>
                        <p className="text-xs text-muted text-balance">
                            Connect to let PostHog access your repos, attribute commits, open pull requests, and assign
                            issues as you. You can add multiple installations for different accounts or organizations.
                        </p>
                    </div>
                ) : (
                    githubIntegrations.map((integration) => (
                        <GitHubInstallationRow key={integration.installation_id} integration={integration} />
                    ))
                )}
                <div className="px-4 py-3">
                    <LemonButton type="secondary" size="small" icon={<IconPlus />} onClick={connectGitHub}>
                        {githubIntegrations.length === 0 ? 'Connect GitHub' : 'Add another installation'}
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
