import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheckCircle, IconGithub, IconPullRequest } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'

import { InstallationProgressView } from './InstallationProgressView'
import { wizardCloudRunLogic } from './wizardCloudRunLogic'
import { WizardModeShell } from './WizardModeShell'

/**
 * The primary, "we'll do it for you" way to run the wizard: connect GitHub, pick a
 * repo, and we run the same instrumentation wizard on our infra and open a pull
 * request you review and merge. Shares WizardModeShell (hog + framework badges)
 * with the local command tab so both read as one wizard.
 *
 * Deliberately non-blocking: kicking off a run flips to live progress — the
 * Installation layer (installationProgressLogic / InstallationProgressView)
 * streams the run's pipeline — and the user can hit Continue right away.
 */
export function WizardCloudRunBlock({
    onQueued,
    hideHog = false,
}: {
    onQueued?: () => void
    hideHog?: boolean
}): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const syncEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    const { githubIntegration, selectedRepository, cloudRunStatus, connectGitHubUrl, cloudRunRunId, cloudRunTaskId } =
        useValues(wizardCloudRunLogic)
    const { setSelectedRepository, startCloudRun } = useActions(wizardCloudRunLogic)

    // Let the install step unblock Continue / hide Skip the moment the run is handed
    // off — the user shouldn't wait on a PR that lands after they've moved on.
    useEffect(() => {
        if (cloudRunStatus === 'queued') {
            onQueued?.()
        }
    }, [cloudRunStatus, onQueued])

    // The cloud wizard only targets cloud (US/EU) and dev instances; nothing to
    // offer on self-hosted.
    if (!isCloudOrDev) {
        return <></>
    }

    if (cloudRunStatus === 'queued') {
        // Once the kickoff returns a run handle, the Installation layer streams the real pipeline
        // (provision → clone → wizard → agent → PR) merged with the wizard session detail.
        if (cloudRunRunId && cloudRunTaskId) {
            return <InstallationProgressView runId={cloudRunRunId} taskId={cloudRunTaskId} />
        }
        const repoLabel = selectedRepository ? <span className="font-mono">{selectedRepository}</span> : 'your repo'
        // A queued run isn't a finished one. With sync on, the install step swaps this block for the
        // live WizardProgressTracker the moment the run's session appears (and the FAB carries it once
        // the user moves on), so we only bridge the brief gap here. Without sync we can't observe the
        // run, so set honest expectations rather than implying the PR is already on its way.
        return (
            <LemonBanner type="info">
                <div className="space-y-1" data-attr="wizard-cloud-run-queued">
                    {syncEnabled ? (
                        <>
                            <div className="font-semibold">Starting your cloud run…</div>
                            <div className="text-sm text-muted">
                                Kicking off the wizard on {repoLabel}. Progress will appear here in a moment and stays in
                                the corner as you keep going.
                            </div>
                        </>
                    ) : (
                        <>
                            <div className="font-semibold">Cloud run queued for {repoLabel}.</div>
                            <div className="text-sm text-muted">
                                If it succeeds we'll open a pull request in your repo to review. We can't show live
                                progress here, so keep an eye on your repository.
                            </div>
                        </>
                    )}
                </div>
            </LemonBanner>
        )
    }

    return (
        <WizardModeShell hideHog={hideHog} data-attr="wizard-cloud-run-block">
            <p className="text-sm text-muted mb-0">
                We'll run the wizard against your repo and open a pull request with the SDK installed and events
                flowing. Review it and merge whenever you're ready.
            </p>

            {!githubIntegration ? (
                <LemonButton
                    type="secondary"
                    icon={<IconGithub />}
                    to={connectGitHubUrl}
                    disableClientSideRouting
                    data-attr="wizard-cloud-run-connect-github"
                    className={hideHog ? 'self-center' : 'self-start'}
                >
                    Connect GitHub
                </LemonButton>
            ) : (
                <div className="flex w-full flex-col gap-2">
                    <div className={`flex items-center gap-1.5 text-xs text-muted ${hideHog ? 'justify-center' : ''}`}>
                        <IconCheckCircle className="text-success" />
                        <span>
                            Connected{githubIntegration.display_name ? ` as ${githubIntegration.display_name}` : ''}
                        </span>
                    </div>
                    <div className="flex items-center gap-2">
                        <div className="flex-1">
                            <GitHubRepositoryPicker
                                integrationId={githubIntegration.id}
                                value={selectedRepository ?? ''}
                                onChange={(repository) => setSelectedRepository(repository)}
                            />
                        </div>
                        <LemonButton
                            type="primary"
                            icon={<IconPullRequest />}
                            onClick={() => startCloudRun()}
                            loading={cloudRunStatus === 'submitting'}
                            disabledReason={selectedRepository ? undefined : 'Pick a repository first'}
                            data-attr="wizard-cloud-run-open-pr"
                        >
                            Open my pull request
                        </LemonButton>
                    </div>
                </div>
            )}
        </WizardModeShell>
    )
}
