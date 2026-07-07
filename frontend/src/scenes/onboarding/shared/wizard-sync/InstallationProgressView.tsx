import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconCheckCircle, IconPullRequest, IconTerminal, IconX } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { activeCloudRunLogic } from './activeCloudRunLogic'
import { prNameLabel } from './helpers'
import {
    InstallationMode,
    InstallationProgress,
    installationProgressLogic,
    InstallationStepStatus,
} from './installationProgressLogic'

// Timeline dot for a single step. `small` is the wizard sub-step size.
function StepIcon({ status, small = false }: { status: InstallationStepStatus; small?: boolean }): JSX.Element {
    const iconSize = small ? 'text-sm' : 'text-base'
    if (status === 'completed') {
        return <IconCheckCircle className={cn('text-success', iconSize)} />
    }
    if (status === 'failed') {
        return <IconX className={cn('text-danger', iconSize)} />
    }
    if (status === 'in_progress') {
        return <Spinner className={iconSize} textColored />
    }
    return <span className={cn('rounded-full border-2 border-border', small ? 'w-3 h-3' : 'w-4 h-4')} />
}

// What's about to happen, shown as pending timeline rows while the stream connects. Same geometry
// (and, for cloud, the same gerund phrasing) as the streamed steps that replace them, so the swap
// reads as the plan lighting up rather than the card rewriting itself. Gerunds also make clear the
// system is the actor — imperatives ("Clone your repository") could read as instructions to the user.
const UPCOMING_STEPS: Record<InstallationMode, string[]> = {
    cloud: ['Setting up sandbox', 'Cloning repository', 'Running setup wizard', 'Opening a pull request'],
    local: ['Detecting your framework', 'Installing the PostHog SDK', 'Wiring up event capture'],
}

const CONNECTING_SUBTITLE: Record<InstallationMode, string> = {
    cloud: 'Firing up a sandbox for your repo – the wizard takes it from there.',
    local: 'Waiting for the wizard in your terminal to check in.',
}

/**
 * Presentational renderer for an `InstallationProgress`: a text header, a connected step timeline, and
 * the terminal payoff (PR link) or failure detail. Pure (no logic/streams) so every state, including
 * the error variants, is storyable in isolation. The container `InstallationProgressView` feeds it live
 * progress from the Installation layer.
 */
export function InstallationProgressContent({
    progress,
    mode,
    onDismiss,
    onRetryLocally,
}: {
    progress: InstallationProgress
    /** Tailors the connecting state (copy + upcoming-step preview) to where the run happens. */
    mode?: InstallationMode
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
                  ? ((mode && CONNECTING_SUBTITLE[mode]) ?? 'Getting things ready…')
                  : phase === 'idle'
                    ? 'Not hearing back from this run right now. You can dismiss it and start over.'
                    : 'Working on it. Feel free to keep going.'

    // Before the stream delivers steps there is nothing moving on screen — carry the "alive" signal in
    // the header, and preview the pipeline so the wait reads as "about to do X", not a mystery.
    const waitingForSteps = steps.length === 0 && (phase === 'connecting' || phase === 'running') && !prReady
    const upcomingSteps = phase === 'connecting' && steps.length === 0 && mode ? UPCOMING_STEPS[mode] : null

    return (
        <div
            className="rounded-lg border border-border bg-bg-light p-4 flex flex-col gap-3"
            data-attr="installation-progress"
        >
            <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2.5 min-w-0">
                    {waitingForSteps && <Spinner className="text-xl shrink-0 mt-0.5 text-accent" textColored />}
                    <div className="min-w-0">
                        <h4 className={cn('font-semibold m-0', phase === 'error' && 'text-danger')}>{headline}</h4>
                        <p className="text-sm text-muted m-0">{subtitle}</p>
                    </div>
                </div>
                {/* Dismiss once the run is settled — mid-run, hiding the only progress surface
                    (the FAB is suppressed while this panel is mounted) would orphan a live run.
                    'idle' is dismissible too: it means the stream stopped permanently without ever
                    delivering state (deleted run, revoked access), and the persisted handle would
                    otherwise be an undismissable zombie across reloads. */}
                {onDismiss && (phase === 'completed' || phase === 'error' || phase === 'idle') && (
                    <LemonButton
                        size="small"
                        icon={<IconX />}
                        onClick={onDismiss}
                        tooltip="Dismiss"
                        aria-label="Dismiss"
                    />
                )}
            </div>

            {steps.length > 0 ? (
                <ol className="flex flex-col m-0 p-0 list-none">
                    {steps.map((step, i) => (
                        // Wizard-reported sub-steps nest a level under the pipeline stage that spawned
                        // them: indented, smaller marker, no rail — read as detail, not more stages.
                        <li key={step.id} className={cn('flex', step.source === 'wizard' ? 'gap-2 pl-7' : 'gap-3')}>
                            <div className="flex flex-col items-center pt-0.5">
                                <StepIcon status={step.status} small={step.source === 'wizard'} />
                                {i < steps.length - 1 && step.source !== 'wizard' && (
                                    <div className="w-px flex-1 bg-border my-1 min-h-[0.75rem]" />
                                )}
                            </div>
                            <div className={cn('flex-1 min-w-0', step.source === 'wizard' ? 'pb-1.5' : 'pb-3')}>
                                <div
                                    className={cn(
                                        step.source === 'wizard' ? 'text-xs' : 'text-sm',
                                        step.status === 'pending' && 'text-muted',
                                        step.status === 'failed' && 'text-danger font-medium',
                                        step.status === 'in_progress' && 'font-medium',
                                        step.source === 'wizard' && step.status === 'completed' && 'text-muted'
                                    )}
                                >
                                    {step.label}
                                </div>
                                {step.detail && <div className="text-xs text-muted truncate">{step.detail}</div>}
                            </div>
                        </li>
                    ))}
                </ol>
            ) : (
                upcomingSteps && (
                    <ol className="flex flex-col m-0 p-0 list-none" aria-label="Upcoming setup steps">
                        {upcomingSteps.map((label, i) => (
                            <li key={label} className="flex gap-3">
                                <div className="flex flex-col items-center pt-0.5">
                                    <StepIcon status="pending" />
                                    {i < upcomingSteps.length - 1 && (
                                        <div className="w-px flex-1 bg-border my-1 min-h-[0.75rem]" />
                                    )}
                                </div>
                                <div className="flex-1 min-w-0 pb-3 text-sm text-muted">{label}</div>
                            </li>
                        ))}
                    </ol>
                )
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
                // ph-no-capture: the label carries the customer's repo name and the href their PR
                // url — neither may reach autocapture in the shared app analytics project.
                <LemonButton
                    type="primary"
                    to={prUrl}
                    targetBlank
                    icon={<IconPullRequest />}
                    center
                    className="ph-no-capture"
                >
                    <span className="truncate">{prNameLabel(prUrl)}</span>
                </LemonButton>
            )}
        </div>
    )
}

/**
 * Container: streams a run's progress from the Installation layer and renders it — the same view for
 * both modes, cloud runs just additionally track the TaskRun pipeline (`mode: 'cloud'` with the run
 * handle; `mode: 'local'` reads only the wizard session stream). Inline on the install step (sets
 * `panelMounted` to hide the floating FAB) or inside the FAB itself (`floating`).
 */
export function InstallationProgressView({
    mode,
    runId,
    taskId,
    floating = false,
    onDismiss,
    onRetryLocally,
}: {
    mode: 'local' | 'cloud'
    /** The TaskRun handle — required for cloud runs, absent for local ones. */
    runId?: string
    taskId?: string
    /** Rendered in the floating FAB rather than inline on the install step. */
    floating?: boolean
    onDismiss?: () => void
    /** Forwarded to the failed-run fallback (see InstallationProgressContent). */
    onRetryLocally?: () => void
}): JSX.Element {
    const { installationProgress } = useValues(installationProgressLogic({ mode, runId, taskId }))
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
            mode={mode}
            onDismiss={onDismiss}
            onRetryLocally={onRetryLocally}
        />
    )
}

/**
 * Whether a local wizard run should take over the install step: a session exists on the stream AND it
 * has been observed fresh (stale terminal rows from previous runs don't count). Mounts the local
 * Installation layer — and with it the wizard session stream — so use it only where the takeover can
 * actually render (the sync-enabled install steps).
 */
export function useLocalWizardRunActive(): boolean {
    const { installationProgress } = useValues(installationProgressLogic({ mode: 'local' }))
    return installationProgress.isCurrent
}
