import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheckCircle, IconPullRequest, IconTerminal, IconX } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { activeCloudRunLogic } from './activeCloudRunLogic'
import { InstallationProgress, installationProgressLogic, InstallationStepStatus } from './installationProgressLogic'

// Timeline dot for a single step.
function StepIcon({ status }: { status: InstallationStepStatus }): JSX.Element {
    if (status === 'completed') {
        return <IconCheckCircle className="text-success text-base" />
    }
    if (status === 'failed') {
        return <IconX className="text-danger text-base" />
    }
    if (status === 'in_progress') {
        return <Spinner className="text-base" textColored />
    }
    return <span className="w-4 h-4 rounded-full border-2 border-border" />
}

/**
 * Presentational renderer for an `InstallationProgress`: a text header, a connected step timeline, and
 * the terminal payoff (PR link) or failure detail. Pure (no logic/streams) so every state, including
 * the error variants, is storyable in isolation. The container `InstallationProgressView` feeds it live
 * progress from the Installation layer.
 */
export function InstallationProgressContent({
    progress,
    onDismiss,
    onRetryLocally,
}: {
    progress: InstallationProgress
    onDismiss?: () => void
    /** When set, a failed run offers a "Run it yourself" button (switches the install step to the local
     * command). Omitted where no local fallback exists (e.g. the floating FAB), which shows only docs. */
    onRetryLocally?: () => void
}): JSX.Element {
    const { phase, steps, error, prUrl } = progress

    // The PR is opened mid-run: while the run keeps going (keeping CI green), surface it as ready rather
    // than an indefinite "setting up". Terminal phases keep their own headline.
    const prReady = !!prUrl && phase !== 'completed' && phase !== 'error'

    const headline =
        phase === 'completed'
            ? 'PostHog is wired up'
            : phase === 'error'
              ? (error?.title ?? "Setup didn't finish")
              : prReady
                ? 'Pull request ready'
                : 'Setting up PostHog'
    const subtitle =
        phase === 'completed'
            ? prUrl
                ? 'We opened a pull request for you to review.'
                : "You're all set."
            : phase === 'error'
              ? "We couldn't finish the setup."
              : prReady
                ? "Review it whenever you like; we'll keep CI green in the meantime."
                : phase === 'connecting'
                  ? 'Getting things ready…'
                  : 'Working on it. Feel free to keep going.'

    return (
        <div
            className="rounded-lg border border-border bg-bg-light p-4 flex flex-col gap-3"
            data-attr="installation-progress"
        >
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                    <h4 className={cn('font-semibold m-0', phase === 'error' && 'text-danger')}>{headline}</h4>
                    <p className="text-sm text-muted m-0">{subtitle}</p>
                </div>
                {/* Dismiss only once the run is settled — mid-run, hiding the only progress surface
                    (the FAB is suppressed while this panel is mounted) would orphan a live run. */}
                {onDismiss && (phase === 'completed' || phase === 'error') && (
                    <LemonButton
                        size="small"
                        icon={<IconX />}
                        onClick={onDismiss}
                        tooltip="Dismiss"
                        aria-label="Dismiss"
                    />
                )}
            </div>

            {steps.length > 0 && (
                <ol className="flex flex-col m-0 p-0 list-none">
                    {steps.map((step, i) => (
                        <li key={step.id} className="flex gap-3">
                            <div className="flex flex-col items-center pt-0.5">
                                <StepIcon status={step.status} />
                                {i < steps.length - 1 && <div className="w-px flex-1 bg-border my-1 min-h-[0.75rem]" />}
                            </div>
                            <div className="flex-1 min-w-0 pb-3">
                                <div
                                    className={cn(
                                        'text-sm',
                                        step.status === 'pending' && 'text-muted',
                                        step.status === 'failed' && 'text-danger font-medium',
                                        step.status === 'in_progress' && 'font-medium'
                                    )}
                                >
                                    {step.label}
                                </div>
                                {step.detail && <div className="text-xs text-muted truncate">{step.detail}</div>}
                            </div>
                        </li>
                    ))}
                </ol>
            )}

            {phase === 'error' && error?.detail && (
                <div className="text-sm text-danger bg-danger-highlight rounded p-2">{error.detail}</div>
            )}

            {phase === 'error' && (
                // The cloud run failed — offer self-serve recovery so the user isn't stuck: run the wizard
                // themselves (switches the install step to the local command) or follow the manual docs.
                <div className="flex flex-wrap gap-2">
                    {onRetryLocally && (
                        <LemonButton type="primary" onClick={onRetryLocally} icon={<IconTerminal />}>
                            Run it yourself
                        </LemonButton>
                    )}
                    <LemonButton
                        type={onRetryLocally ? 'secondary' : 'primary'}
                        to="https://posthog.com/docs/getting-started/install"
                        targetBlank
                    >
                        Read the docs
                    </LemonButton>
                </div>
            )}

            {prUrl && (
                <LemonButton type="primary" to={prUrl} targetBlank icon={<IconPullRequest />} center>
                    Review PR
                </LemonButton>
            )}
        </div>
    )
}

/**
 * Container: streams a cloud run's progress from the Installation layer and renders it. Inline on the
 * install step (sets `panelMounted` to hide the floating FAB) or inside the FAB itself (`floating`).
 */
export function InstallationProgressView({
    runId,
    taskId,
    floating = false,
    onDismiss,
    onRetryLocally,
}: {
    runId: string
    taskId: string
    /** Rendered in the floating FAB rather than inline on the install step. */
    floating?: boolean
    onDismiss?: () => void
    /** Forwarded to the failed-run fallback (see InstallationProgressContent). */
    onRetryLocally?: () => void
}): JSX.Element {
    const { installationProgress } = useValues(installationProgressLogic({ mode: 'cloud', runId, taskId }))
    const { setPanelMounted } = useActions(activeCloudRunLogic)

    // While shown inline on the install step, hide the floating FAB so the same run isn't in two places.
    useEffect(() => {
        if (floating) {
            return
        }
        setPanelMounted(true)
        return () => setPanelMounted(false)
    }, [floating, setPanelMounted])

    return (
        <InstallationProgressContent
            progress={installationProgress}
            onDismiss={onDismiss}
            onRetryLocally={onRetryLocally}
        />
    )
}
