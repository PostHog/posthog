import { useActions, useValues } from 'kea'

import { LemonButton, LemonCard, LemonTag, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { supportSettingsLogic } from './supportSettingsLogic'

export function GithubSection(): JSX.Element {
    return (
        <SceneSection
            title="GitHub Issues"
            description={
                <>
                    Connect a GitHub App installation to sync issues as support tickets. Comments sync bidirectionally —
                    replies from PostHog appear on the GitHub issue.
                </>
            }
        >
            <LemonCard hoverEffect={false} className="flex flex-col gap-y-2 max-w-[800px] px-4 py-3">
                <GithubConnectionSection />
            </LemonCard>
        </SceneSection>
    )
}

function GithubConnectionSection(): JSX.Element {
    const { githubConnected, githubRepos, githubReposLoading, githubSelectedRepos, githubIntegrations } =
        useValues(supportSettingsLogic)
    const { connectGithub, disconnectGithub, setGithubRepos, loadGithubRepos } = useActions(supportSettingsLogic)
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    if (!githubConnected) {
        if (githubIntegrations.length === 0) {
            return (
                <div className="flex flex-col gap-y-2">
                    <label className="font-medium">Connection</label>
                    <p className="text-xs text-muted-alt">
                        First, install the PostHog GitHub App from the integrations page, then come back here to select
                        which repositories to monitor.
                    </p>
                    <Link to="/settings/project-integrations" className="mt-1">
                        <LemonButton type="primary" size="small" disabledReason={adminRestrictionReason}>
                            Go to integrations
                        </LemonButton>
                    </Link>
                </div>
            )
        }

        return (
            <div className="flex flex-col gap-y-2">
                <label className="font-medium">Connection</label>
                <p className="text-xs text-muted-alt">
                    Select a GitHub App installation to connect. Issues from selected repositories will become support
                    tickets.
                </p>
                <div className="flex flex-wrap gap-2 mt-1">
                    {githubIntegrations.map((integration) => (
                        <LemonButton
                            key={integration.id}
                            type="primary"
                            size="small"
                            disabledReason={adminRestrictionReason}
                            onClick={() => connectGithub(integration.id)}
                        >
                            Connect {integration.name || `Installation #${integration.id}`}
                        </LemonButton>
                    ))}
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-y-4">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <label className="font-medium mb-0">GitHub Issues</label>
                    <LemonTag type="success" size="small">
                        Connected
                    </LemonTag>
                </div>
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    status="danger"
                    disabledReason={adminRestrictionReason}
                    onClick={() => {
                        LemonDialog.open({
                            title: 'Disconnect GitHub?',
                            description:
                                'New issues will no longer create tickets. Existing tickets will remain but replies will not sync.',
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

            <div>
                <label className="font-medium">Monitored repositories</label>
                <p className="text-xs text-muted-alt mb-2">
                    Select which repositories to watch for new issues. Only issues from these repos will create tickets.
                </p>
                <LemonInputSelect
                    mode="multiple"
                    value={githubSelectedRepos}
                    onChange={(values) => setGithubRepos(values)}
                    options={githubRepos.map((r) => ({ key: r.full_name, label: r.full_name }))}
                    loading={githubReposLoading}
                    onFocus={loadGithubRepos}
                    placeholder="Select repositories..."
                    disabled={!!adminRestrictionReason}
                />
            </div>
        </div>
    )
}
