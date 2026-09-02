import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'

import type { FinishedLocalRunHandle } from './finishedLocalRunLogic'
import { startedByFromSession } from './helpers'
import type {
    InstallationPhase,
    InstallationProgress,
    InstallationStep,
    InstallationStepStatus,
    WizardPendingInput,
} from './installationProgressLogic'
import { taskRunPrMerged, taskRunPrUrl, TaskRunProgressStep, TaskRunStreamState } from './taskRunStreamLogic'

/**
 * Pure builders that turn the raw streams (TaskRun pipeline, wizard session) into the one normalized
 * `InstallationProgress` the UI renders. No kea, no I/O — `installationProgressLogic` wires these to
 * its connected values, and the tests exercise them directly.
 */

// A session counts as "current" if it was updated within the last 10 minutes. Lets the install step
// ignore stale terminal sessions left over from previous runs / test data when a user lands on the
// app, while still re-surfacing recently-completed runs after a quick navigation away and back.
const SESSION_CURRENT_THRESHOLD_MS = 10 * 60 * 1000

export function isSessionFresh(session: WizardSessionDTOApi, now: number): boolean {
    const updatedAt = new Date(session.updated_at).getTime()
    return !Number.isNaN(updatedAt) && now - updatedAt < SESSION_CURRENT_THRESHOLD_MS
}

// Tolerance for the sandbox clock minting `started_at` slightly behind our kickoff stamp.
const RUN_SESSION_SKEW_MS = 5 * 60 * 1000

// Whether a session belongs to this cloud run: it started inside the run's own window. Used for
// the handoff doc, which must outlive the recency gate — the wizard stage ends hours before the
// pipeline does, so by completion the session is long past `isSessionFresh`, yet its doc is still
// this run's report. A session from a previous run keeps failing this check by starting earlier.
export function isSessionFromRun(session: WizardSessionDTOApi, runStartedAt: string): boolean {
    const sessionStart = new Date(session.started_at).getTime()
    const runStart = new Date(runStartedAt).getTime()
    return !Number.isNaN(sessionStart) && !Number.isNaN(runStart) && sessionStart >= runStart - RUN_SESSION_SKEW_MS
}

// A dead wizard can't clear its own prompt (the clearing push never arrives), so the attention state
// must go quiet with the session: gated on the server's staleness verdict and a live (running) phase.
export function pendingInputFromSession(session: WizardSessionDTOApi | null): WizardPendingInput | null {
    if (!session || session.is_stale || session.run_phase !== 'running') {
        return null
    }
    const raw = session.pending_input
    if (!raw?.id) {
        return null
    }
    // The prompt text goes straight into JSX, and the type is the serializer's promise rather than a
    // runtime guarantee, so keep non-strings out: a row written before the field was typed would
    // otherwise crash the render of an app-wide widget.
    const prompts = Array.isArray(raw.prompts) ? raw.prompts.filter((p): p is string => typeof p === 'string') : []
    return {
        id: raw.id,
        askedAt: raw.asked_at ?? session.updated_at,
        questionCount: raw.question_count ?? 1,
        sensitive: raw.sensitive === true,
        prompts: raw.sensitive === true ? [] : prompts,
    }
}

const STEP_STATUSES: Record<string, InstallationStepStatus> = {
    pending: 'pending',
    in_progress: 'in_progress',
    completed: 'completed',
    failed: 'failed',
    canceled: 'failed',
}

// The stages every cloud run walks, in order — the timeline's fixed plan. Labels match the
// connecting preview (UPCOMING_STEPS) so the handoff between the two is seamless; announced steps
// override them with the backend's own labels.
const CLOUD_PIPELINE_SKELETON: { group: string; step: string; label: string }[] = [
    { group: 'setup', step: 'sandbox', label: 'Setting up sandbox' },
    { group: 'setup', step: 'clone', label: 'Cloning repository' },
    { group: 'setup', step: 'wizard', label: 'Running setup wizard' },
    { group: 'deliver', step: 'pr', label: 'Opening a pull request' },
]

function stepStatus(raw: string): InstallationStepStatus {
    return STEP_STATUSES[raw] ?? 'pending'
}

// Cloud: the TaskRun is the spine (phase, steps, PR url, terminal error); the wizard session's own
// tasks expand into the timeline as wizard-sourced steps nested after the pipeline's wizard stage
// (absent while the cloud wizard hasn't reported yet — degrades to the bare TaskRun pipeline).
export function cloudProgress(
    taskRunState: TaskRunStreamState | null,
    progressSteps: TaskRunProgressStep[],
    taskConnectionStatus: string,
    latestSession: WizardSessionDTOApi | null,
    isStalled: boolean = false,
    now: number = Date.now(),
    /** When this run kicked off (from the persisted handle) — scopes the handoff doc to the run. */
    runStartedAt: string | null = null
): InstallationProgress {
    let phase: InstallationPhase
    let stalledError: { title: string; detail: string | null } | null = null
    if (!taskRunState && isStalled) {
        // The stream never delivered any run state (deleted or access-revoked run, a stream that
        // stayed silent past taskRunStreamLogic's no-state window). `idle` renders as a spinner with
        // no way out, so surface the dead end: the error phase carries the retry CTAs and the
        // dismiss control.
        phase = 'error'
        stalledError = {
            title: 'Setup lost contact',
            detail: 'We stopped hearing back from this run. Run the wizard yourself, or dismiss it and start over.',
        }
    } else if (!taskRunState) {
        phase = taskConnectionStatus === 'connecting' ? 'connecting' : 'idle'
    } else if (taskRunState.status === 'queued' && isStalled) {
        // The run never left the queue (see taskRunStreamLogic's stall timer) — nothing is actually
        // running, so an eternal spinner would be a lie.
        phase = 'error'
        stalledError = {
            title: "Setup hasn't started",
            detail: 'The run has been queued for a while without starting. Please try again in a bit.',
        }
    } else if (taskRunState.status === 'completed') {
        phase = 'completed'
    } else if (taskRunState.status === 'failed' || taskRunState.status === 'cancelled') {
        phase = 'error'
    } else if (taskRunState.status === 'queued') {
        // Queued means nothing has started yet — "getting ready", not "running".
        phase = 'connecting'
    } else {
        phase = 'running'
    }

    // A completed run has nothing in flight: clamp a lingering in-progress step (e.g. "Keeping
    // CI green", emitted in-progress when the PR opened) to completed so the timeline matches.
    const clamp = (status: InstallationStepStatus): InstallationStepStatus =>
        phase === 'completed' && status === 'in_progress' ? 'completed' : status

    // 'Started agent' is internal plumbing — it tells the user nothing about their setup. Hide it;
    // the pending "Opening a pull request" row (flipped in-progress below) narrates that window.
    const announced = progressSteps.filter((p) => p.step !== 'agent')
    const mapStep = (p: TaskRunProgressStep): InstallationStep => ({
        id: `${p.group}:${p.step}`,
        label: p.label,
        status: clamp(stepStatus(p.status)),
        // The "pr" step carries the PR url in `detail` (surfaced as the CTA, not as raw step text).
        detail: p.step === 'pr' ? null : p.detail,
    })
    // Every cloud run walks the same pipeline, so the whole plan is visible from the start as
    // pending rows — announced steps light their slot up in place (keeping the backend's label and
    // detail), and anything outside the skeleton (e.g. "Keeping CI green") appends in arrival
    // order. Skipped when no run state exists yet: the view's connecting preview owns that window.
    let pipelineSteps: InstallationStep[]
    if (taskRunState) {
        const byName = new Map(announced.map((p) => [p.step, p]))
        pipelineSteps = CLOUD_PIPELINE_SKELETON.map((sk) => {
            const real = byName.get(sk.step)
            return real
                ? mapStep(real)
                : { id: `${sk.group}:${sk.step}`, label: sk.label, status: 'pending' as const, detail: null }
        })
        const skeletonNames = new Set(CLOUD_PIPELINE_SKELETON.map((sk) => sk.step))
        pipelineSteps.push(...announced.filter((p) => !skeletonNames.has(p.step)).map(mapStep))
    } else {
        pipelineSteps = announced.map(mapStep)
    }

    // The session stream is keyed by workflow only and replays the latest session on connect even
    // when it's a stale terminal row from a previous (possibly local) run — apply the same freshness
    // gate the local path uses before letting it near this run's timeline or error detail. A fresh
    // unrelated session can still slip in (the cloud wizard posts to the same workflow by design).
    const session = latestSession && isSessionFresh(latestSession, now) ? latestSession : null

    // The cloud wizard reports its own sub-steps on the session stream — once they exist they
    // REPLACE the pipeline's aggregate "wizard" stage in the timeline (the tasks are that stage,
    // told in more detail). Until then the stage row stands in. When the stage hasn't been
    // announced at all (e.g. polling mode where step notifications are stream-borne), slot the
    // tasks before the first not-yet-completed pipeline step so in-flight wizard work never
    // renders after the PR stage.
    const wizardSteps: InstallationStep[] = (session?.tasks ?? []).map((t) => ({
        id: `wizard-task:${t.id}`,
        label: t.title,
        status: clamp(stepStatus(t.status)),
        detail: null,
        source: 'wizard',
    }))
    const wizardStageIndex = pipelineSteps.findIndex((s) => s.id.endsWith(':wizard'))
    let steps: InstallationStep[]
    if (wizardStageIndex !== -1 && wizardSteps.length > 0) {
        steps = [
            ...pipelineSteps.slice(0, wizardStageIndex),
            ...wizardSteps,
            ...pipelineSteps.slice(wizardStageIndex + 1),
        ]
    } else if (wizardSteps.length > 0) {
        const firstUnfinished = pipelineSteps.findIndex((s) => s.status !== 'completed')
        const insertIndex = firstUnfinished === -1 ? pipelineSteps.length : firstUnfinished
        steps = [...pipelineSteps.slice(0, insertIndex), ...wizardSteps, ...pipelineSteps.slice(insertIndex)]
    } else {
        steps = pipelineSteps
    }

    const prUrl = taskRunPrUrl(taskRunState, progressSteps)
    const prMerged = taskRunPrMerged(taskRunState)

    // A merged PR ends the story: the CI-babysitting row would otherwise keep spinning forever
    // (the workflow's follow-up loop skips closed PRs, so nothing will ever complete it).
    if (prMerged) {
        steps = steps.filter((s) => !s.id.endsWith(':ci'))
    }

    // The pipeline goes quiet between agent start and the PR opening: everything reads completed
    // while the agent is still writing code, committing, and drafting the PR — which looks stalled.
    // Flip the still-pending PR slot to in-progress with an honest detail line for that window; the
    // real deliver-stage step replaces it when it arrives.
    const allDoneExceptPr = steps.every((s) => s.id.endsWith(':pr') || s.status === 'completed')
    if (phase === 'running' && !prUrl && allDoneExceptPr) {
        steps = steps.map((s) =>
            s.id.endsWith(':pr') && s.status === 'pending'
                ? {
                      ...s,
                      status: 'in_progress' as const,
                      detail: 'The agent is committing its changes and drafting the PR',
                  }
                : s
        )
    }

    const error =
        phase === 'error'
            ? (stalledError ?? {
                  // A cancelled run is a deliberate stop (Cancel button or closing the setup PR),
                  // not a broken installation — presenting it as a failure reads as a bug.
                  title: taskRunState?.status === 'cancelled' ? 'Run cancelled' : 'Installation failed',
                  detail:
                      taskRunState?.error_message ?? (session?.error as { message?: string } | null)?.message ?? null,
              })
            : null

    // The doc rides the run-window check, not the recency gate: the cloud wizard finishes (and
    // publishes its report) hours before the pipeline completes, so by the time the completed
    // surfaces would show the button the session is long stale. Without a run window (no handle),
    // fall back to the recency-gated session rather than trusting an arbitrary old row.
    const handoffSession =
        latestSession && runStartedAt !== null
            ? isSessionFromRun(latestSession, runStartedAt)
                ? latestSession
                : null
            : session

    return {
        phase,
        steps,
        error,
        prUrl,
        prMerged,
        isCurrent: phase !== 'idle',
        pendingInput: phase === 'running' ? pendingInputFromSession(session) : null,
        startedBy: startedByFromSession(session),
        handoffText: handoffSession?.handoff_text ?? null,
    }
}

// Local: the wizard session is the only source. `sessionIsCurrent` is the sticky freshness flag —
// the SSE replays the latest session on connect even when it's a stale terminal row from a previous
// run, and those must not read as a run in flight. `dismissed` is the user's explicit dismissal of
// this session — it wins over freshness, so a dismissed run releases the install-step takeover.
export function localProgress(
    latestSession: WizardSessionDTOApi | null,
    sessionConnectionStatus: string,
    sessionIsCurrent: boolean,
    dismissed: boolean = false
): InstallationProgress {
    if (!latestSession) {
        return {
            phase: sessionConnectionStatus === 'connecting' ? 'connecting' : 'idle',
            steps: [],
            error: null,
            prUrl: null,
            prMerged: false,
            isCurrent: false,
            pendingInput: null,
            startedBy: null,
            handoffText: null,
        }
    }

    // A CLI that dies without pushing a terminal phase leaves the row mid-run forever. The server
    // computes staleness against the same threshold the detector trusts, so treat it the way the
    // cloud path treats a stalled run: surface the dead end, because `connecting` and `running` both
    // render as a spinner that `InstallationProgressContent` offers no way out of.
    const stalled = latestSession.is_stale && latestSession.run_phase !== 'completed'

    let phase: InstallationPhase
    if (latestSession.run_phase === 'completed') {
        phase = 'completed'
    } else if (latestSession.run_phase === 'error' || stalled) {
        phase = 'error'
    } else if (sessionConnectionStatus === 'connecting' || sessionConnectionStatus === 'error') {
        phase = 'connecting'
    } else {
        phase = 'running'
    }

    const steps: InstallationStep[] = (latestSession.tasks ?? []).map((t) => ({
        id: t.id,
        label: t.title,
        status: stepStatus(t.status),
        detail: null,
    }))

    let error: { title: string; detail: string | null } | null = null
    if (latestSession.run_phase === 'error') {
        error = {
            title: 'Wizard hit an error',
            detail: (latestSession.error as { message?: string } | null)?.message ?? null,
        }
    } else if (stalled) {
        error = {
            title: 'Setup lost contact',
            detail: 'We stopped hearing back from this run. Run the wizard yourself, or dismiss it and start over.',
        }
    }

    return {
        phase,
        steps,
        error,
        prUrl: null,
        prMerged: false,
        isCurrent: sessionIsCurrent && !dismissed,
        pendingInput: phase === 'running' && !dismissed ? pendingInputFromSession(latestSession) : null,
        startedBy: startedByFromSession(latestSession),
        handoffText: latestSession.handoff_text ?? null,
    }
}

// A finished local run rendered from its persisted snapshot, after the live session stream has
// gated itself off — same shape the live path produces for the same terminal session.
export function progressFromFinishedLocalRun(handle: FinishedLocalRunHandle): InstallationProgress {
    return {
        phase: handle.runPhase,
        steps: handle.tasks.map((t) => ({ id: t.id, label: t.title, status: stepStatus(t.status), detail: null })),
        error:
            handle.runPhase === 'error'
                ? { title: 'Wizard hit an error', detail: handle.error?.message ?? null }
                : null,
        prUrl: null,
        prMerged: false,
        isCurrent: true,
        pendingInput: null,
        startedBy: handle.startedBy ?? null,
        handoffText: handle.handoffText ?? null,
    }
}
