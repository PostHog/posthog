import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonSelect, LemonTag, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { FeatureRequestApi } from '../../generated/api.schemas'
import { FeatureRequestDetailSection } from './FeatureRequestDetailSection'
import { featureRequestGithubLogic } from './featureRequestGithubLogic'

export function FeatureRequestGithubSection({ request }: { request: FeatureRequestApi }): JSX.Element {
    const logic = featureRequestGithubLogic({ requestId: request.id })
    const {
        githubIntegrations,
        integrationsLoading,
        issueUrl,
        selectedIntegrationId,
        mutationError,
        mutationIsStale,
        mutatingGithubLink,
        canUpdate,
        linkDisabledReason,
    } = useValues(logic)
    const {
        setIssueUrl,
        setIntegrationId,
        linkGithub,
        pauseGithub,
        resumeGithub,
        unlinkGithub,
        reloadLatestGithubLink,
    } = useActions(logic)
    const githubLink = request.github_link
    const disabledReason = request.is_archived
        ? 'Restore this request to update GitHub sync'
        : canUpdate
          ? undefined
          : 'You do not have permission to update this request'

    return (
        <FeatureRequestDetailSection icon={<IconGithub />} title="GitHub issue">
            <div className="flex min-w-0 flex-col gap-3">
                {mutationError && (
                    <LemonBanner type="error">
                        <div className="flex flex-wrap items-center gap-2">
                            <span>{mutationError}</span>
                            {mutationIsStale && (
                                <LemonButton
                                    type="secondary"
                                    size="xsmall"
                                    onClick={reloadLatestGithubLink}
                                    data-attr="reload-feature-request-github-link"
                                >
                                    Reload
                                </LemonButton>
                            )}
                        </div>
                    </LemonBanner>
                )}
                {githubLink ? (
                    <>
                        <div className="flex min-w-0 flex-wrap items-center gap-2">
                            <LemonButton
                                type="tertiary"
                                size="small"
                                to={githubLink.issue_url}
                                targetBlank
                                className="min-w-0 max-w-full truncate"
                            >
                                {`${githubLink.repository}#${githubLink.issue_number}${
                                    githubLink.issue_title ? `: ${githubLink.issue_title}` : ''
                                }`}
                            </LemonButton>
                            <LemonTag type={githubLink.issue_state === 'open' ? 'success' : 'muted'}>
                                {githubLink.issue_state === 'open' ? 'Open' : 'Closed'}
                            </LemonTag>
                            <LemonTag type={githubLink.sync_enabled ? 'primary' : 'muted'}>
                                {githubLink.sync_enabled ? 'Syncing' : 'Sync paused'}
                            </LemonTag>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={githubLink.sync_enabled ? pauseGithub : resumeGithub}
                                loading={mutatingGithubLink}
                                disabledReason={disabledReason}
                                data-attr={
                                    githubLink.sync_enabled
                                        ? 'pause-feature-request-github-sync'
                                        : 'resume-feature-request-github-sync'
                                }
                            >
                                {githubLink.sync_enabled ? 'Pause sync' : 'Resume sync'}
                            </LemonButton>
                            <LemonButton
                                type="tertiary"
                                size="small"
                                onClick={unlinkGithub}
                                loading={mutatingGithubLink}
                                disabledReason={disabledReason}
                                data-attr="unlink-feature-request-github-issue"
                            >
                                Unlink issue
                            </LemonButton>
                        </div>
                    </>
                ) : integrationsLoading ? (
                    <span className="text-secondary">Loading GitHub integrations.</span>
                ) : githubIntegrations.length === 0 ? (
                    <LemonBanner type="info">
                        Connect GitHub in <Link to={urls.integration('github')}>settings</Link> to link an issue.
                    </LemonBanner>
                ) : (
                    <>
                        <span className="text-secondary">Link this request to a GitHub issue.</span>
                        {githubIntegrations.length > 1 && (
                            <LemonSelect<number>
                                value={selectedIntegrationId ?? undefined}
                                onChange={(integrationId) => setIntegrationId(integrationId ?? null)}
                                options={githubIntegrations.map((integration) => ({
                                    value: integration.id,
                                    label: integration.display_name,
                                }))}
                                placeholder="Select a GitHub integration"
                                fullWidth
                            />
                        )}
                        <div className="flex flex-wrap gap-2">
                            <LemonInput
                                value={issueUrl}
                                onChange={setIssueUrl}
                                placeholder="https://github.com/owner/repo/issues/123"
                                className="min-w-0 flex-1 basis-64"
                            />
                            <LemonButton
                                type="primary"
                                size="small"
                                onClick={linkGithub}
                                loading={mutatingGithubLink}
                                disabledReason={linkDisabledReason}
                                data-attr="link-feature-request-github-issue"
                            >
                                Link issue
                            </LemonButton>
                        </div>
                    </>
                )}
            </div>
        </FeatureRequestDetailSection>
    )
}
