import { type ReactNode } from 'react'

import * as wizardPng from '@posthog/brand/hoggies/png/wizard-1'
import { IconDocument, IconPullRequest, IconRocket, IconSearch, IconTerminal, IconX } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { cn } from 'lib/utils/css-classes'

import { CheckList } from '../components/CheckList'
import { prNameLabel } from './helpers'
import { useMergeCelebration } from './hooks'
import { SELF_DRIVING_UPCOMING_STEPS, syncCopy, UPCOMING_STEPS } from './installationProgressCopy'
import { InstallationMode, InstallationProgress } from './installationProgressLogic'
import { StepIcon } from './StepIcon'
import { Timeline } from './Timeline'
import { resolveWorkflowId, SELF_DRIVING_WORKFLOW_ID } from './workflows'

const HedgehogWizard = pngHoggie(wizardPng)

/**
 * Presentational renderer for an `InstallationProgress`: a text header, a connected step timeline, and
 * the terminal payoff (PR link) or failure detail. No logic or streams, so every state, including the
 * error variants, is storyable in isolation. The container `InstallationProgressView` feeds it live
 * progress from the Installation layer.
 */
export function InstallationProgressContent({
    workflowId,
    continueHint,
    progress,
    mode,
    onViewReport,
    onDismiss,
    onRetryLocally,
}: {
    progress: InstallationProgress
    /** Tailors the connecting state (copy + upcoming-step preview) to where the run happens. */
    mode?: InstallationMode
    /** Wizard program being watched — picks the copy, since the programs do different work. */
    workflowId?: string
    /** Shown while the run is in flight, to say it keeps going if the user navigates away. */
    continueHint?: ReactNode
    /** Opens the run's handoff doc (the setup report) — the completed state's payoff. Only rendered
     * when the progress actually carries a doc. */
    onViewReport?: () => void
    onDismiss?: () => void
    /** When set, a failed run offers a "Run it yourself" button (switches the install step to the local
     * command). Omitted where no local fallback exists (e.g. the floating FAB), which shows only docs. */
    onRetryLocally?: () => void
}): JSX.Element {
    const { phase, steps, error, prUrl, prMerged } = progress

    // The PR is opened mid-run: while the run keeps going (keeping CI green), surface it as ready rather
    // than an indefinite "setting up". Terminal phases keep their own headline.
    const prReady = !!prUrl && phase !== 'completed' && phase !== 'error'

    // Celebrate a merge the user performs while watching, exactly once per mount.
    const { CelebrationComponent } = useMergeCelebration(prMerged)

    const selfDriving = resolveWorkflowId(workflowId) === SELF_DRIVING_WORKFLOW_ID
    const { headline, subtitle } = syncCopy({ progress, mode, selfDriving, prReady })

    // Before the stream delivers steps there is nothing moving on screen — carry the "alive" signal in
    // the header, and preview the pipeline so the wait reads as "about to do X", not a mystery.
    const waitingForSteps = steps.length === 0 && (phase === 'connecting' || phase === 'running') && !prReady
    // Preview the plan for the whole gap before the first real step arrives, not just while
    // connecting: a run that has started but not yet reported leaves the card otherwise empty.
    const upcomingSteps =
        waitingForSteps && mode ? (selfDriving ? SELF_DRIVING_UPCOMING_STEPS : UPCOMING_STEPS[mode]) : null

    return (
        <div
            className="rounded-lg border border-border bg-bg-light p-4 flex flex-col gap-3"
            data-attr="installation-progress"
        >
            <CelebrationComponent />
            <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2.5 min-w-0">
                    {waitingForSteps && <Spinner className="text-xl shrink-0 mt-0.5 text-accent" textColored />}
                    <div className="min-w-0">
                        <h4 className={cn('font-semibold m-0', phase === 'error' && 'text-danger')}>{headline}</h4>
                        <p className="text-sm text-muted m-0">{subtitle}</p>
                    </div>
                </div>
                <div className="flex items-start gap-1 shrink-0">
                    {phase === 'completed' && <HedgehogWizard className="w-14 h-14 -my-2" aria-hidden="true" />}
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
            </div>

            {steps.length > 0 ? (
                // One flat rail for pipeline and wizard-reported steps alike.
                <Timeline
                    items={steps.map((step) => ({
                        key: step.id,
                        icon: (
                            <StepIcon
                                status={step.status}
                                prState={step.id.endsWith(':pr') && prUrl ? (prMerged ? 'merged' : 'open') : undefined}
                            />
                        ),
                        content: (
                            <div
                                className={cn(
                                    'text-sm truncate flex items-center gap-1.5',
                                    step.status === 'pending' && 'text-muted',
                                    step.status === 'failed' && 'text-danger font-medium',
                                    step.status === 'in_progress' && 'font-medium'
                                )}
                            >
                                <span className="truncate">
                                    {step.id.endsWith(':pr') && prMerged ? 'PR merged, congratulations!' : step.label}
                                </span>
                            </div>
                        ),
                        detail: step.detail && (
                            <div className="text-xs text-muted truncate ph-no-capture">{step.detail}</div>
                        ),
                    }))}
                />
            ) : (
                upcomingSteps && (
                    <Timeline
                        ariaLabel="Upcoming setup steps"
                        items={upcomingSteps.map((label) => ({
                            key: label,
                            icon: <StepIcon status="pending" />,
                            content: <div className="text-sm text-muted">{label}</div>,
                        }))}
                    />
                )
            )}

            {continueHint && phase !== 'completed' && phase !== 'error' && (
                <p className="text-xs text-muted m-0 border-t border-border pt-3">{continueHint}</p>
            )}

            {phase === 'completed' &&
                mode === 'local' && (
                    // The wizard's changes sit uncommitted on the user's machine — only the user can
                    // finish the last mile (review, deploy), so no button can carry this step.
                    <div className="flex flex-col gap-1.5">
                        <span className="text-xs font-semibold uppercase tracking-wide text-muted">Over to you</span>
                        <CheckList
                            items={[
                                {
                                    icon: <IconSearch className="text-muted" />,
                                    content: (
                                        <span>
                                            <strong>Review the changes</strong> in your editor before you commit.
                                        </span>
                                    ),
                                },
                                {
                                    icon: <IconTerminal className="text-muted" />,
                                    content: (
                                        <span>
                                            <strong>Try it locally</strong> and your events show up here right away.
                                        </span>
                                    ),
                                },
                                {
                                    icon: <IconRocket className="text-muted" />,
                                    content: (
                                        <span>
                                            <strong>Commit and deploy</strong> to get data from real users.
                                        </span>
                                    ),
                                },
                            ]}
                        />
                    </div>
                )}

            {phase === 'error' && error?.detail && (
                <LemonBanner type="error" hideIcon>
                    {error.detail}
                </LemonBanner>
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

            {prUrl &&
                !prMerged &&
                phase !== 'error' && (
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

            {prUrl && prMerged && phase !== 'error' && (
                <LemonBanner type="success" icon={<IconPullRequest />} className="ph-no-capture">
                    {/* ph-no-capture: the action href is the customer's PR url. */}
                    <div className="flex items-center gap-3">
                        <div className="flex-1 min-w-0">
                            <div className="text-sm font-semibold">Pull request successfully merged</div>
                            <div className="text-xs font-normal">
                                You're all set. Deploy the changes and your events start flowing.
                            </div>
                        </div>
                        <LemonButton type="secondary" size="small" to={prUrl} targetBlank className="shrink-0">
                            View PR
                        </LemonButton>
                    </div>
                </LemonBanner>
            )}

            {phase === 'completed' && progress.handoffText && onViewReport && (
                <LemonButton
                    type={prUrl ? 'secondary' : 'primary'}
                    onClick={onViewReport}
                    icon={<IconDocument />}
                    center
                    data-attr="wizard-sync-view-report"
                >
                    View setup report
                </LemonButton>
            )}
        </div>
    )
}
