import { useActions, useMountedLogic, useValues } from 'kea'

import { Badge, Button, Chip, ChipClose, ChipGroup, Skeleton, Text } from '@posthog/quill'

import { GitHubRepositoryCombobox } from 'lib/integrations/GitHubRepositoryCombobox'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { MAX_GITHUB_REPOS, githubReposLogic } from './githubReposLogic'
import { QuillRetryText } from './QuillRetryText'

export function QuillGithubReposSetting({ onDisconnect }: { onDisconnect: () => void }): JSX.Element {
    useMountedLogic(integrationsLogic)
    const { githubIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const { connection, connectionLoading, draftRepos, saving, connecting, disconnecting } = useValues(githubReposLogic)
    const { addRepo, removeRepo, saveRepos, connectGithub, loadConnection } = useActions(githubReposLogic)

    if (connectionLoading && !connection) {
        return <Skeleton className="h-16 w-full max-w-xl" />
    }

    if (!connection) {
        return <QuillRetryText message="Couldn't load GitHub repositories." onRetry={() => loadConnection()} />
    }

    if (!connection.connected) {
        if (integrationsLoading && githubIntegrations.length === 0) {
            return <Skeleton className="h-16 w-full max-w-xl" />
        }

        if (githubIntegrations.length === 0) {
            return (
                <Text size="xs" render={<p className="m-0" />}>
                    <Button
                        variant="link"
                        size="inline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.settings('project-integrations')} />}
                    >
                        Install the PostHog GitHub App
                    </Button>
                    , then come back here to choose repositories.
                </Text>
            )
        }

        return (
            <div className="flex flex-wrap gap-2">
                {githubIntegrations.map((integration) => (
                    <Button
                        key={integration.id}
                        variant="primary"
                        loading={connecting}
                        disabledReason={connecting ? 'Connecting GitHub' : undefined}
                        onClick={() => connectGithub(integration.id)}
                        data-attr="business-knowledge-github-connect"
                    >
                        {`Connect ${integration.display_name || `installation ${integration.id}`}`}
                    </Button>
                ))}
            </div>
        )
    }

    if (connection.integration_id == null) {
        return <QuillRetryText message="Couldn't load the GitHub connection." onRetry={() => loadConnection()} />
    }

    const saved = connection.repos
    const changed = saved.length !== draftRepos.length || saved.some((repo, index) => repo !== draftRepos[index])
    const atCap = draftRepos.length >= MAX_GITHUB_REPOS

    return (
        <div className="flex flex-col gap-2 max-w-xl">
            <div className="flex flex-wrap items-center gap-2">
                <Text size="xs" weight="medium" render={<span />}>
                    {connection.integration_name || 'GitHub'}
                </Text>
                <Badge variant="success">Connected</Badge>
                <Button
                    variant="destructive-outline"
                    size="sm"
                    loading={disconnecting}
                    disabledReason={disconnecting ? 'Disconnecting GitHub' : undefined}
                    data-attr="business-knowledge-github-disconnect"
                    onClick={onDisconnect}
                >
                    Disconnect
                </Button>
            </div>
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                {`Choose up to ${MAX_GITHUB_REPOS} repositories. Business knowledge searches file names and the README, then reads a file.`}
            </Text>
            {draftRepos.length > 0 ? (
                <ChipGroup className="flex-wrap">
                    {draftRepos.map((repo) => (
                        <Chip key={repo}>
                            {repo}
                            <ChipClose
                                aria-label={`Remove ${repo}`}
                                onClick={() => removeRepo(repo)}
                                disabledReason={saving ? 'Saving repositories' : undefined}
                            />
                        </Chip>
                    ))}
                </ChipGroup>
            ) : null}
            <div className="flex flex-wrap items-center gap-2">
                <GitHubRepositoryCombobox
                    integrationId={connection.integration_id}
                    value=""
                    onChange={(fullName) => {
                        if (fullName) {
                            addRepo(fullName)
                        }
                    }}
                    repositoryFilter={(repository) => !draftRepos.includes(repository.full_name.toLowerCase())}
                    loadAll
                    disabled={saving || atCap}
                    disabledReason={atCap ? `You can select up to ${MAX_GITHUB_REPOS} repositories` : undefined}
                    placeholder="Add a repository"
                />
                <Button
                    variant="primary"
                    loading={saving}
                    disabledReason={
                        !changed ? 'No repository changes to save' : saving ? 'Saving repositories' : undefined
                    }
                    onClick={saveRepos}
                    data-attr="business-knowledge-github-save-repos"
                >
                    Save repositories
                </Button>
            </div>
        </div>
    )
}
