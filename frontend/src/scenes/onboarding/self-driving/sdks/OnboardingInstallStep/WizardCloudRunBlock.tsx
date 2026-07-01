import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconCheckCircle, IconChevronDown, IconGithub, IconPullRequest } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'

import { activeCloudRunLogic } from './activeCloudRunLogic'
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
    onRetryLocally,
}: {
    onQueued?: () => void
    hideHog?: boolean
    /** Forwarded to the install progress view so a failed run can offer "Run it yourself". */
    onRetryLocally?: () => void
}): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const syncEnabled = useFeatureFlag('ONBOARDING_WIZARD_SYNC', 'test')
    const { githubIntegration, selectedRepository, cloudRunStatus, connectGitHubUrl } = useValues(wizardCloudRunLogic)
    const { activeCloudRun } = useValues(activeCloudRunLogic)
    const { setSelectedRepository, startCloudRun } = useActions(wizardCloudRunLogic)

    // Fire onQueued once per kickoff, the moment the run is handed off. It advances the install step
    // (GROW-96), so it must not repeat while the status stays 'queued' (the callback identity changes
    // each render). Reset when the run leaves 'queued' so a later run can advance the flow again.
    const queuedAdvancedRef = useRef(false)
    useEffect(() => {
        if (cloudRunStatus === 'queued') {
            if (!queuedAdvancedRef.current) {
                queuedAdvancedRef.current = true
                onQueued?.()
            }
        } else {
            queuedAdvancedRef.current = false
        }
    }, [cloudRunStatus, onQueued])

    // The cloud wizard only targets cloud (US/EU) and dev instances; nothing to
    // offer on self-hosted.
    if (!isCloudOrDev) {
        return <></>
    }

    // A spawned run (persisted handle) shows live progress and survives revisits, where the local
    // cloudRunStatus resets. While a run is active the parent blocks the local command (GROW-95), so
    // this is the only thing the cloud tab shows.
    if (activeCloudRun) {
        return (
            <InstallationProgressView
                runId={activeCloudRun.runId}
                taskId={activeCloudRun.taskId}
                onRetryLocally={onRetryLocally}
            />
        )
    }

    if (cloudRunStatus === 'queued') {
        const repoLabel = selectedRepository ? <span className="font-mono">{selectedRepository}</span> : 'your repo'
        // The brief window after kickoff before the run handle settles. With sync on the Installation
        // layer takes over above; without sync we cannot observe the run, so set honest expectations.
        return (
            <LemonBanner type="info">
                <div className="space-y-1" data-attr="wizard-cloud-run-queued">
                    {syncEnabled ? (
                        <>
                            <div className="font-semibold">Starting your cloud run…</div>
                            <div className="text-sm text-muted">
                                Kicking off the wizard on {repoLabel}. Progress will appear here in a moment and stays
                                in the corner as you keep going.
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
                We'll run the wizard against your repo and open a pull request with the SDK installed and your context
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
                    <div className="flex items-center gap-2">
                        <div className="relative flex-1">
                            <IconGithub className="absolute left-2 top-1/2 -translate-y-1/2 z-10 text-base text-muted pointer-events-none" />
                            <GitHubRepositoryPicker
                                integrationId={githubIntegration.id}
                                value={selectedRepository ?? ''}
                                onChange={(repository) => setSelectedRepository(repository)}
                                // Make the combobox read as a dropdown, not a text field: the LemonInput
                                // root defaults to `cursor: text` (unlayered SCSS), so override with `!`.
                                className="pl-7 pr-7 !cursor-pointer"
                            />
                            {!selectedRepository && (
                                <IconChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 z-10 text-base text-muted pointer-events-none" />
                            )}
                        </div>
                        <LemonButton
                            type="primary"
                            icon={<IconPullRequest />}
                            onClick={() => startCloudRun()}
                            loading={cloudRunStatus === 'submitting'}
                            disabledReason={selectedRepository ? undefined : 'Pick a repository first'}
                            data-attr="wizard-cloud-run-open-pr"
                        >
                            Install PostHog here
                        </LemonButton>
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-muted">
                        <IconCheckCircle className="text-success" />
                        <span>
                            Connected{githubIntegration.display_name ? ` to ${githubIntegration.display_name}` : ''}
                        </span>
                    </div>
                </div>
            )}
        </WizardModeShell>
    )
}
