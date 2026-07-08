import { InstallationProgress, InstallationStep, InstallationStepStatus } from './installationProgressLogic'

// "m:ss", or "h:mm:ss" once a run passes the hour mark (cloud runs can be long).
export function formatElapsed(totalSeconds: number): string {
    const s = Math.max(0, Math.floor(totalSeconds))
    const hours = Math.floor(s / 3600)
    const minutes = Math.floor((s % 3600) / 60)
    const seconds = s % 60
    const ss = seconds.toString().padStart(2, '0')
    if (hours > 0) {
        return `${hours}:${minutes.toString().padStart(2, '0')}:${ss}`
    }
    return `${minutes}:${ss}`
}

// The short status line shown in the collapsed card header.
export function syncHeadline(progress: InstallationProgress): string {
    if (progress.phase === 'completed') {
        return 'PostHog is set up'
    }
    if (progress.phase === 'error') {
        return progress.error?.title ?? 'Setup hit a snag'
    }
    if (progress.prUrl) {
        return 'Pull request ready'
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
    if (progress.phase === 'completed') {
        return progress.prUrl ? 'Pull request is ready to review' : 'Everything is wired up'
    }
    if (progress.phase === 'error') {
        return progress.error?.detail ?? 'Something stopped the run'
    }
    const step = activeStep(progress.steps)
    if (step) {
        return step.detail ?? step.label
    }
    return progress.phase === 'connecting' ? 'Connecting to your run' : 'Getting things ready'
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
