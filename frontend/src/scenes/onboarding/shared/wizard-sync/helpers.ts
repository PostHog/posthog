import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import type { InstallationProgress, InstallationStep, InstallationStepStatus } from './installationProgressLogic'
import type { TaskRunConnectionStatus } from './taskRunStreamLogic'

// Prefer a real name; fall back to email so we never render a blank attribution.
export function startedByFromSession(session: WizardSessionDTOApi | null): { name: string; email: string } | null {
    const createdBy = session?.created_by
    if (!createdBy) {
        return null
    }
    return { name: createdBy.first_name || createdBy.email, email: createdBy.email }
}

// Ceiling on the displayed elapsed time. The clock is driven by a persisted handle that outlives the
// run it names, so without a cap a run nobody ever settled counts up for as long as the browser keeps
// the handle. Display only: telemetry keeps the true elapsed.
export const MAX_DISPLAY_ELAPSED_SECONDS = 6 * 60 * 60

// "m:ss", or "h:mm:ss" once a run passes the hour mark (cloud runs can be long). Anything past the
// display cap reads as the cap with a trailing "+".
export function formatElapsed(totalSeconds: number): string {
    const raw = Math.max(0, Math.floor(totalSeconds))
    const s = Math.min(MAX_DISPLAY_ELAPSED_SECONDS, raw)
    const hours = Math.floor(s / 3600)
    const minutes = Math.floor((s % 3600) / 60)
    const seconds = s % 60
    const ss = seconds.toString().padStart(2, '0')
    const clamped = raw > s ? '+' : ''
    if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, '0')}:${ss}${clamped}`
    }
    return `${minutes}:${ss}${clamped}`
}

// Silence alone says nothing about a cloud run: the pipeline is designed to go quiet for long
// stretches, publishing nothing between the agent starting and the PR opening, and its CI follow-up
// loop sleeps a quarter hour at a time. So the silence window only counts while the stream that
// would carry those updates is down, and it is set wider than the longest designed quiet period.
// The age cap is the second, independent gate, for a handle that survived a day of reloads without
// its run ever settling.
export const STALE_RUN_SILENCE_MS = 30 * 60 * 1000
export const STALE_RUN_MAX_AGE_MS = 24 * 60 * 60 * 1000

/**
 * Whether the transport that would carry a run's updates is down, which is what turns silence into
 * evidence. `idle` and `connecting` are the states every stream passes through before it has had a
 * chance to say anything, including on each mount of a run that is already hours old and on every
 * reconnect in between: counting them would call a healthy long run stale for the length of a
 * connect, and offer a dismiss that orphans it. A stream that never gets past them is still caught,
 * by `isStalled`, which the run logic sets once it gives up.
 */
export function isStreamLost(status: TaskRunConnectionStatus, isStalled: boolean): boolean {
    return isStalled || status === 'error' || status === 'closed'
}

/**
 * Whether a still-running run has gone stale, meaning its surfaces should offer a dismiss instead of
 * only a minimize. `lastActivityAt` is when the stream last delivered anything (null when it never
 * has, in which case the handle's kickoff stamp stands in), and `streamLost` says whether the
 * transport that would deliver more is down right now. The stamp is a client clock and the silence
 * window is wide enough to absorb the skew against it.
 */
export function isRunStale(
    startedAt: string | undefined,
    lastActivityAt: number | null,
    streamLost: boolean,
    now: number
): boolean {
    const startedMs = startedAt ? new Date(startedAt).getTime() : NaN
    if (!Number.isNaN(startedMs) && now - startedMs > STALE_RUN_MAX_AGE_MS) {
        return true
    }
    if (!streamLost) {
        return false
    }
    const silentSince = lastActivityAt ?? startedMs
    return !Number.isNaN(silentSince) && now - silentSince > STALE_RUN_SILENCE_MS
}

// What the widgets print where the elapsed clock goes. A stale run's clock is meaningless, so it is
// replaced by the reason it stopped mattering.
export function elapsedLabel(elapsedSeconds: number, stale: boolean = false): string {
    return stale ? 'Stalled' : formatElapsed(elapsedSeconds)
}

// The short status line shown in the collapsed card header.
export function syncHeadline(progress: InstallationProgress): string {
    if (progress.phase === 'completed') {
        return 'PostHog is set up'
    }
    if (progress.phase === 'error') {
        return progress.error?.title ?? 'Setup hit a snag'
    }
    if (progress.prMerged) {
        return 'Pull request merged'
    }
    if (progress.prUrl) {
        return 'Pull request ready'
    }
    if (progress.pendingInput) {
        return 'Waiting for your answer'
    }
    if (progress.phase === 'connecting') {
        return 'Getting ready'
    }
    return 'Setting up PostHog'
}

export function activeStep(steps: InstallationStep[]): InstallationStep | null {
    const inProgress = steps.filter((s) => s.status === 'in_progress')
    // Prefer the wizard's own sub-step over the pipeline stage that contains it — "Installing the
    // SDK" says more than "Running setup wizard" when both are in flight.
    return inProgress.find((s) => s.source === 'wizard') ?? inProgress[0] ?? null
}

// The prominent line: the active step's live detail (the wizard's current sub-task) when present,
// otherwise the step label. This is what gives the wizard's own work top billing in the card.
export function currentTaskLabel(progress: InstallationProgress): string | null {
    if (progress.phase === 'error') {
        return progress.error?.detail ?? 'Something stopped the run'
    }
    if (progress.prMerged) {
        return 'PR merged, congratulations!'
    }
    if (progress.phase === 'completed') {
        return progress.prUrl ? 'Pull request is ready to review' : 'Everything is wired up'
    }
    if (progress.pendingInput) {
        // The run is blocked and the user is usually looking at the app, not the terminal, so the
        // prominent line is the call to go back there. The question itself is secondary, since
        // knowing there is one is what unblocks the run.
        return 'Your terminal needs your attention'
    }
    const step = activeStep(progress.steps)
    if (step) {
        return step.detail ?? step.label
    }
    return progress.phase === 'connecting' ? 'Connecting to your run' : 'Getting things ready'
}

/**
 * The pending question, shown below the call to action rather than in place of it. Null when nothing
 * is pending and for sensitive asks, which publish no prompt text at all.
 */
export function pendingQuestionLabel(progress: InstallationProgress): string | null {
    return progress.pendingInput?.prompts[0] ?? null
}

export function stepCounts(steps: InstallationStep[]): { completed: number; total: number } {
    return {
        completed: steps.filter((s) => s.status === 'completed').length,
        total: steps.length,
    }
}

// "owner/repo#123" from a GitHub-style PR url, or null when it doesn't parse (self-hosted forges,
// unexpected shapes) — callers fall back to a generic label. The name makes the CTA concrete: the
// user may have kicked off runs against more than one repo, and "Review PR" doesn't say which.
export function prName(url: string): string | null {
    const match = url.match(/^https?:\/\/[^/]+\/([^/]+)\/([^/]+)\/pull\/(\d+)(?:[/?#]|$)/)
    return match ? `${match[1]}/${match[2]}#${match[3]}` : null
}

// The review CTA's label, shared by the inline view and the sync card.
export function prNameLabel(prUrl: string): string {
    const name = prName(prUrl)
    return name ? `Review ${name}` : 'Review PR'
}

// Accent tone for the whole widget, driven by phase. One accent plus the two terminal colors keeps it
// colorful without going loud.
export function toneTextClass(progress: InstallationProgress): string {
    if (progress.phase === 'completed') {
        return 'text-success'
    }
    if (progress.phase === 'error') {
        return 'text-danger'
    }
    if (progress.pendingInput) {
        return 'text-warning'
    }
    return 'text-accent'
}

// Fill color for a single progress pip, one per step.
export function pipClass(status: InstallationStepStatus): string {
    switch (status) {
        case 'completed':
            return 'bg-success'
        case 'in_progress':
            return 'bg-accent animate-pulse'
        case 'failed':
            return 'bg-danger'
        default:
            return 'bg-border'
    }
}

export function localModeLabel(startedByLabel?: string | null): string {
    return startedByLabel ? `On ${startedByLabel}'s machine` : 'On your machine'
}

/** The teammate's name, or null for the viewer's own run (matched on email) or an unknown initiator. */
export function resolveStartedByLabel(
    startedBy: InstallationProgress['startedBy'],
    currentUserEmail: string | undefined
): string | null {
    if (!startedBy || startedBy.email === currentUserEmail) {
        return null
    }
    return startedBy.name
}
