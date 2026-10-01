import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonSkeleton, LemonSnack, LemonTag, Link } from '@posthog/lemon-ui'

import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { urls } from 'scenes/urls'

import { MAX_GITHUB_REPOS, githubReposLogic } from './githubReposLogic'

export function GithubReposSetting(): JSX.Element {
    useMountedLogic(integrationsLogic)
    const { githubIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const { connection, connectionLoading, draftRepos, saving, connecting, disconnecting } = useValues(githubReposLogic)
    const { addRepo, removeRepo, saveRepos, connectGithub, disconnectGithub, loadConnection } =
        useActions(githubReposLogic)

    if (connectionLoading && !connection) {
        return <LemonSkeleton className="h-16 w-full max-w-xl" />
    }
    if (!connection) {
        return (
            <p className="m-0">
                Couldn't load GitHub repositories. <Link onClick={() => loadConnection()}>Try again</Link>
            </p>
        )
    }
    if (!connection.connected) {
        if (integrationsLoading && githubIntegrations.length === 0) {
            return <LemonSkeleton className="h-16 w-full max-w-xl" />
        }
        if (githubIntegrations.length === 0) {
            return (
                <p className="m-0">
                    <Link to={urls.settings('project-integrations')}>Install the PostHog GitHub App</Link>, then come
                    back here to choose repositories.
                </p>
            )
        }
        return (
            <div className="flex flex-wrap gap-2">
                {githubIntegrations.map((integration) => (
                    <LemonButton
                        key={integration.id}
                        type="primary"
                        size="small"
                        loading={connecting}
                        disabledReason={connecting ? 'Connecting GitHub' : undefined}
                        onClick={() => connectGithub(integration.id)}
                        data-attr="business-knowledge-github-connect"
                    >
                        Connect {integration.display_name || `installation ${integration.id}`}
                    </LemonButton>
                ))}
            </div>
        )
    }

    if (connection.integration_id == null) {
        return (
            <p className="m-0">
                Couldn't load the GitHub connection. <Link onClick={() => loadConnection()}>Try again</Link>
            </p>
        )
    }

    const saved = connection.repos
    const changed = saved.length !== draftRepos.length || saved.some((repo, index) => repo !== draftRepos[index])
    const atCap = draftRepos.length >= MAX_GITHUB_REPOS

    return (
        <div className="flex flex-col gap-2 max-w-xl">
            <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{connection.integration_name || 'GitHub'}</span>
                <LemonTag type="success" size="small">
                    Connected
                </LemonTag>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    status="danger"
                    loading={disconnecting}
                    disabledReason={disconnecting ? 'Disconnecting GitHub' : undefined}
                    data-attr="business-knowledge-github-disconnect"
                    onClick={() => {
                        LemonDialog.open({
                            title: 'Disconnect GitHub?',
                            description:
                                'Business knowledge will stop reading these repositories. The GitHub App stays installed.',
                            primaryButton: {
                                children: 'Disconnect',
                                status: 'danger',
                                onClick: disconnectGithub,
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }}
                >
                    Disconnect
                </LemonButton>
            </div>
            <p className="text-xs text-muted m-0">
                Choose up to {MAX_GITHUB_REPOS} repositories. Business knowledge searches file names and the README,
                then reads a file.
            </p>
            <div className="flex flex-wrap gap-1">
                {draftRepos.map((repo) => (
                    <LemonSnack key={repo} onClose={saving ? undefined : () => removeRepo(repo)}>
                        {repo}
                    </LemonSnack>
                ))}
            </div>
            <GitHubRepositoryCombobox
                integrationId={connection.integration_id}
                value=""
                onChange={(fullName) => {
                    if (fullName) {
                        addRepo(fullName)
                    }
                }}
                disabled={saving || atCap}
                disabledReason={atCap ? `You can select up to ${MAX_GITHUB_REPOS} repositories` : undefined}
                placeholder="Add a repository"
            />
            <div>
                <LemonButton
                    type="primary"
                    size="small"
                    loading={saving}
                    disabledReason={
                        !changed ? 'No repository changes to save' : saving ? 'Saving repositories' : undefined
                    }
                    onClick={saveRepos}
                    data-attr="business-knowledge-github-save-repos"
                >
                    Save repositories
                </LemonButton>
            </div>
        </div>
    )
}
