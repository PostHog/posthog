import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheckCircle, IconGithub, IconPullRequest } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { GitHubRepositoryPicker } from 'lib/integrations/GitHubIntegrationHelpers'
import { useWizardCommand } from 'scenes/onboarding/shared/SetupWizardBanner'

import { wizardCloudRunLogic } from './wizardCloudRunLogic'
import { WizardModeShell } from './WizardModeShell'

/**
 * The primary, "we'll do it for you" way to run the wizard: connect GitHub, pick a
 * repo, and we run the same instrumentation wizard on our infra and open a pull
 * request you review and merge. Shares WizardModeShell (hog + framework badges)
 * with the local command tab so both read as one wizard.
 *
 * Deliberately non-blocking: kicking off a run flips to a queued acknowledgement
 * and the user can hit Continue right away. Live progress and the "your PR is
 * ready" payoff are carried by the shared session-sync surfaces (the global FAB),
 * not by this block — see wizardCloudRunLogic.
 */
export function WizardCloudRunBlock({
    onQueued,
    hideHog = false,
}: {
    onQueued?: () => void
    hideHog?: boolean
}): JSX.Element {
    const { isCloudOrDev } = useWizardCommand()
    const { githubIntegration, selectedRepository, cloudRunStatus, connectGitHubUrl } = useValues(wizardCloudRunLogic)
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
        return (
            <LemonBanner type="success">
                <div className="space-y-1" data-attr="wizard-cloud-run-queued">
                    <div className="font-semibold">On it – your pull request is on the way.</div>
                    <div className="text-sm text-muted">
                        We're instrumenting{' '}
                        {selectedRepository ? <span className="font-mono">{selectedRepository}</span> : 'your repo'} and
                        will open a PR with PostHog wired up. Keep going – we'll let you know the moment it's ready to
                        review.
                    </div>
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
                    className="self-start"
                >
                    Connect GitHub
                </LemonButton>
            ) : (
                <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-1.5 text-xs text-muted">
                        <IconCheckCircle className="text-success" />
                        <span>
                            Connected{githubIntegration.display_name ? ` as ${githubIntegration.display_name}` : ''}
                        </span>
                    </div>
                    <GitHubRepositoryPicker
                        integrationId={githubIntegration.id}
                        value={selectedRepository ?? ''}
                        onChange={(repository) => setSelectedRepository(repository)}
                    />
                    <LemonButton
                        type="primary"
                        icon={<IconPullRequest />}
                        onClick={() => startCloudRun()}
                        loading={cloudRunStatus === 'submitting'}
                        disabledReason={selectedRepository ? undefined : 'Pick a repository first'}
                        data-attr="wizard-cloud-run-open-pr"
                        className="self-start"
                    >
                        Open my pull request
                    </LemonButton>
                </div>
            )}
        </WizardModeShell>
    )
}
