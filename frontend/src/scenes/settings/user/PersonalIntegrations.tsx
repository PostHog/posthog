import { useActions, useValues } from 'kea'

import { IconGithub, IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDialog, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { GitHubRepoSummary } from 'lib/integrations/GitHubRepoSummary'
import { userGithubIntegrationLogic } from 'lib/integrations/userGithubIntegrationLogic'

import { personalIntegrationsLogic, PersonalGitHubIntegration } from './personalIntegrationsLogic'

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
                        repoNames={repositories.map((r) => r.name)}
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

export function PersonalIntegrations(): JSX.Element {
    const { integrations, integrationsLoading } = useValues(personalIntegrationsLogic)
    const { connectGitHub } = useActions(personalIntegrationsLogic)

    if (integrationsLoading && integrations.length === 0) {
        return (
            <div className="deprecated-space-y-2">
                <LemonSkeleton className="h-16 w-full" />
            </div>
        )
    }

    return (
        <div className="deprecated-space-y-3">
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
                    integrations.map((integration) => (
                        <GitHubInstallationRow key={integration.installation_id} integration={integration} />
                    ))
                )}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3">
                    <LemonButton type="secondary" size="small" icon={<IconPlus />} onClick={connectGitHub}>
                        {integrations.length === 0 ? 'Connect GitHub' : 'Add account/organization'}
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
