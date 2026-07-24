import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { currentTaskLabel } from 'scenes/onboarding/shared/wizard-sync/helpers'
import { InstallationProgress } from 'scenes/onboarding/shared/wizard-sync/installationProgressLogic'

// A cloud run's status at quickstart altitude: healthy-and-working, failed-with-a-way-out,
// or finished-with-the-PR. Sub-step detail stays behind the header chip's dialog.
export function QuickstartRunStatus({
    progress,
    onRetryLocally,
}: {
    progress: InstallationProgress
    onRetryLocally: () => void
}): JSX.Element {
    if (progress.error) {
        return (
            <div className="flex flex-col gap-2" role="status">
                <div className="font-semibold text-sm">{progress.error.title}</div>
                {progress.error.detail && <p className="text-secondary text-sm mb-0">{progress.error.detail}</p>}
                <div>
                    <LemonButton type="secondary" size="small" onClick={onRetryLocally}>
                        Run it in your terminal instead
                    </LemonButton>
                </div>
            </div>
        )
    }
    if (progress.prUrl) {
        // Merging, deploying, and the first event all happen outside our sight, so this is
        // the terminal state from our side: hand over the PR and let the user take it from there.
        const match = progress.prUrl.match(/github\.com\/([^/]+\/[^/]+)\/pull\/(\d+)/)
        return (
            <div className="flex flex-col gap-2" role="status">
                <div className="font-semibold text-sm">The agent opened a pull request</div>
                <p className="text-secondary text-sm mb-0">
                    Review the changes, merge, and deploy. Events start flowing once your app runs with the new code.
                </p>
                {match && (
                    <div className="text-sm text-secondary font-mono">
                        {match[1]} #{match[2]}
                    </div>
                )}
                <div className="w-fit">
                    <LemonButton type="primary" size="small" to={progress.prUrl} targetBlank>
                        Review the pull request
                    </LemonButton>
                </div>
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-3" role="status" aria-live="polite" data-attr="quickstart-run-status">
            <div className="flex items-center gap-2">
                <Spinner className="text-base" />
                <span className="text-sm font-medium">
                    {progress.steps.length > 0
                        ? 'The agent is working on your integration'
                        : (currentTaskLabel(progress) ?? 'The agent is working on your integration')}
                </span>
            </div>
            {progress.steps.length > 0 && (
                <ul className="flex flex-col gap-1.5 mb-0">
                    {progress.steps.map((step) => (
                        <li key={step.id} className="flex items-start gap-2 text-sm">
                            {step.status === 'completed' ? (
                                <IconCheckCircle className="text-success mt-0.5 shrink-0" />
                            ) : step.status === 'in_progress' ? (
                                <Spinner className="mt-0.5 shrink-0" />
                            ) : (
                                <span className="mt-1.5 ml-0.5 size-1.5 rounded-full bg-muted-alt shrink-0" />
                            )}
                            <span className="min-w-0">
                                <span
                                    className={
                                        step.status === 'pending'
                                            ? 'text-muted'
                                            : step.status === 'completed'
                                              ? 'text-secondary'
                                              : 'text-primary font-medium'
                                    }
                                >
                                    {step.label}
                                </span>
                                {step.status === 'in_progress' && step.detail && (
                                    <span className="block text-xs text-secondary truncate">{step.detail}</span>
                                )}
                            </span>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}
