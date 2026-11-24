import { Badge, Button, FieldContent, FieldDescription, FieldTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { QuillGithubRepoField } from '../QuillGithubRepoField/QuillGithubRepoField'
import { QuillSettingsSubsection } from '../QuillSettingsSubsection/QuillSettingsSubsection'

interface GithubIntegration {
    id: number
    name?: string | null
}

export function QuillGithubSection({
    githubConnected,
    githubIntegrations,
    githubRepoNames,
    githubReposLoading,
    githubSelectedRepos,
    adminRestrictionReason,
    onConnect,
    onDisconnect,
    onReposChange,
    onLoadRepos,
}: {
    githubConnected: boolean
    githubIntegrations: GithubIntegration[]
    githubRepoNames: string[]
    githubReposLoading: boolean
    githubSelectedRepos: string[]
    adminRestrictionReason: string | null
    onConnect: (integrationId: number) => void
    onDisconnect: () => void
    onReposChange: (repos: string[]) => void
    onLoadRepos: () => void
}): JSX.Element {
    return (
        <QuillSettingsSubsection
            title="GitHub Issues"
            description="Connect a GitHub App installation to sync issues as support tickets. Comments sync bidirectionally — replies from PostHog appear on the GitHub issue."
        >
            {!githubConnected ? (
                <div className="flex flex-col gap-2">
                    <FieldContent>
                        <FieldTitle>Connection</FieldTitle>
                        <FieldDescription>
                            {githubIntegrations.length === 0
                                ? 'First, install the PostHog GitHub App from the integrations page, then come back here to select which repositories to monitor.'
                                : 'Select a GitHub App installation to connect. Issues from selected repositories will become support tickets.'}
                        </FieldDescription>
                    </FieldContent>
                    <div className="flex flex-wrap gap-2">
                        {githubIntegrations.length === 0 ? (
                            <Button
                                variant="primary"
                                nativeButton={false}
                                render={<LinkPrimitive to="/integrations/github" />}
                                disabledReason={adminRestrictionReason}
                            >
                                Go to GitHub integration
                            </Button>
                        ) : (
                            githubIntegrations.map((integration) => (
                                <Button
                                    key={integration.id}
                                    variant="primary"
                                    disabledReason={adminRestrictionReason}
                                    onClick={() => onConnect(integration.id)}
                                >
                                    Connect {integration.name || `Installation #${integration.id}`}
                                </Button>
                            ))
                        )}
                    </div>
                </div>
            ) : (
                <div className="flex flex-col gap-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                            <FieldTitle>GitHub Issues</FieldTitle>
                            <Badge variant="success">Connected</Badge>
                        </div>
                        <Button
                            variant="destructive-outline"
                            disabledReason={adminRestrictionReason}
                            onClick={onDisconnect}
                        >
                            Disconnect
                        </Button>
                    </div>
                    <QuillGithubRepoField
                        repoNames={githubRepoNames}
                        loading={githubReposLoading}
                        value={githubSelectedRepos}
                        disabledReason={adminRestrictionReason}
                        onChange={onReposChange}
                        onOpen={onLoadRepos}
                    />
                </div>
            )}
        </QuillSettingsSubsection>
    )
}
