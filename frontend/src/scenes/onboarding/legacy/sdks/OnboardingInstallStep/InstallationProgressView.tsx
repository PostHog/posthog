import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheckCircle, IconPullRequest, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { cn } from 'lib/utils/css-classes'

import { activeCloudRunLogic } from './activeCloudRunLogic'
import {
    InstallationPhase,
    InstallationProgress,
    installationProgressLogic,
    InstallationStepStatus,
} from './installationProgressLogic'

// Header badge — a tinted disc whose icon reflects the overall phase.
function StatusBadge({ phase }: { phase: InstallationPhase }): JSX.Element {
    const base = 'w-8 h-8 rounded-full flex items-center justify-center shrink-0'
    if (phase === 'completed') {
        return (
            <span className={cn(base, 'bg-success-highlight')}>
                <IconCheckCircle className="text-success text-lg" />
            </span>
        )
    }
    if (phase === 'error') {
        return (
            <span className={cn(base, 'bg-danger-highlight')}>
                <IconWarning className="text-danger text-lg" />
            </span>
        )
    }
    return (
        <span className={cn(base, 'bg-border')}>
            <Spinner />
        </span>
    )
}

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
 * Presentational renderer for an `InstallationProgress`: a status header, a progress bar, a connected
 * step timeline, and the terminal payoff (PR link) or failure detail. Pure (no logic/streams) so every
 * state, including the error variants, is storyable in isolation. The container `InstallationProgressView`
 * feeds it live progress from the Installation layer.
 */
export function InstallationProgressContent({
    progress,
    onDismiss,
}: {
    progress: InstallationProgress
    onDismiss?: () => void
}): JSX.Element {
    const { phase, steps, error, prUrl } = progress

    const total = steps.length
    const completedCount = steps.filter((s) => s.status === 'completed').length
    const percent = total > 0 ? Math.round((completedCount / total) * 100) : 0

    const headline =
        phase === 'completed'
            ? 'PostHog is wired up'
            : phase === 'error'
              ? (error?.title ?? "Setup didn't finish")
              : 'Setting up PostHog'
    const subtitle =
        phase === 'completed'
            ? prUrl
                ? 'We opened a pull request for you to review.'
                : "You're all set."
            : phase === 'error'
              ? "We couldn't finish the setup."
              : phase === 'connecting'
                ? 'Getting things ready…'
                : 'Working on it — feel free to keep going.'

    return (
        <div className="rounded-lg border border-border bg-bg-light p-4 flex flex-col gap-4" data-attr="installation-progress">
            <div className="flex items-start gap-3">
                <StatusBadge phase={phase} />
                <div className="flex-1 min-w-0">
                    <h4 className="font-semibold m-0">{headline}</h4>
                    <p className="text-sm text-muted m-0">{subtitle}</p>
                </div>
                {onDismiss && (
                    <LemonButton size="small" icon={<IconX />} onClick={onDismiss} tooltip="Dismiss" aria-label="Dismiss" />
                )}
            </div>

            {total > 0 && (phase === 'running' || phase === 'completed') && (
                <LemonProgress percent={percent} strokeColor={phase === 'completed' ? 'var(--success)' : undefined} />
            )}

            {total > 0 && (
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

            {phase === 'completed' && prUrl && (
                <LemonButton type="primary" to={prUrl} targetBlank icon={<IconPullRequest />} center>
                    Review pull request
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
}: {
    runId: string
    taskId: string
    /** Rendered in the floating FAB rather than inline on the install step. */
    floating?: boolean
    onDismiss?: () => void
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

    return <InstallationProgressContent progress={installationProgress} onDismiss={onDismiss} />
}
