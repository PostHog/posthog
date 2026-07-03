import { afterMount, beforeUnmount, connect, kea, key, path, props, selectors } from 'kea'

import type { WizardSessionDTOApi } from 'products/wizard/frontend/generated/api.schemas'
import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

import type { installationProgressLogicType } from './installationProgressLogicType'
import { taskRunStreamLogic, TaskRunProgressStep, TaskRunStreamState } from './taskRunStreamLogic'

// The wizard session stream the local CLI publishes to — and the channel a cloud wizard reports its
// own sub-progress on. Matches wizardProgressTrackerLogic's WORKFLOW_ID.
const WORKFLOW_ID = 'posthog-integration'

export type InstallationMode = 'local' | 'cloud'
export type InstallationPhase = 'idle' | 'connecting' | 'running' | 'completed' | 'error'
export type InstallationStepStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

export interface InstallationStep {
    id: string
    label: string
    status: InstallationStepStatus
    detail: string | null
}

export interface InstallationProgress {
    phase: InstallationPhase
    steps: InstallationStep[]
    error: { title: string; detail: string | null } | null
    prUrl: string | null
    isCurrent: boolean
}

export interface InstallationProgressLogicProps {
    mode: InstallationMode
    runId?: string
    taskId?: string
}

const STEP_STATUSES: Record<string, InstallationStepStatus> = {
    pending: 'pending',
    in_progress: 'in_progress',
    completed: 'completed',
    failed: 'failed',
    canceled: 'failed',
}

function stepStatus(raw: string): InstallationStepStatus {
    return STEP_STATUSES[raw] ?? 'pending'
}

// Cloud: the TaskRun is the spine (phase, steps, PR url, terminal error); the wizard session enriches
// the wizard stage with its live sub-task (absent today while the cloud wizard is WIP — degrades to
// the bare TaskRun step).
export function cloudProgress(
    taskRunState: TaskRunStreamState | null,
    progressSteps: TaskRunProgressStep[],
    taskConnectionStatus: string,
    latestSession: WizardSessionDTOApi | null,
    isStalled: boolean = false
): InstallationProgress {
    let phase: InstallationPhase
    let stalledError: { title: string; detail: string | null } | null = null
    if (!taskRunState) {
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

    const wizardDetail =
        latestSession?.tasks?.find((t) => t.status === 'in_progress')?.title ??
        (latestSession?.run_phase === 'error' ? 'Wizard hit an error' : null)

    const steps: InstallationStep[] = progressSteps.map((p) => {
        const status = stepStatus(p.status)
        return {
            id: `${p.group}:${p.step}`,
            label: p.label,
            // A completed run has nothing in flight: clamp a lingering in-progress step (e.g. "Keeping
            // CI green", emitted in-progress when the PR opened) to completed so the timeline matches.
            status: phase === 'completed' && status === 'in_progress' ? 'completed' : status,
            // The "pr" step carries the PR url in `detail` (surfaced as the CTA, not as raw step text).
            detail:
                p.step === 'pr'
                    ? null
                    : p.step === 'wizard' && p.status === 'in_progress'
                      ? (wizardDetail ?? p.detail)
                      : p.detail,
        }
    })

    const error =
        phase === 'error'
            ? (stalledError ?? {
                  title: 'Installation failed',
                  detail:
                      taskRunState?.error_message ??
                      (latestSession?.error as { message?: string } | null)?.message ??
                      null,
              })
            : null

    // The agent opens the PR mid-run (while it keeps CI green), so the url arrives via the "pr" progress
    // step before the run reaches a terminal output. Prefer the terminal output when present.
    const prStepUrl = progressSteps.find((p) => p.step === 'pr')?.detail
    const prUrl = taskRunState?.output?.pr_url ?? (prStepUrl && prStepUrl.startsWith('http') ? prStepUrl : null)

    return {
        phase,
        steps,
        error,
        prUrl,
        isCurrent: phase !== 'idle',
    }
}

// Local: the wizard session is the only source — mirror wizardProgressTrackerLogic's displayState so
// the existing surfaces behave identically when they migrate onto this layer.
export function localProgress(
    latestSession: WizardSessionDTOApi | null,
    sessionConnectionStatus: string
): InstallationProgress {
    if (!latestSession) {
        return {
            phase: sessionConnectionStatus === 'connecting' ? 'connecting' : 'idle',
            steps: [],
            error: null,
            prUrl: null,
            isCurrent: false,
        }
    }

    let phase: InstallationPhase
    if (latestSession.run_phase === 'completed') {
        phase = 'completed'
    } else if (latestSession.run_phase === 'error') {
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

    const error =
        latestSession.run_phase === 'error'
            ? {
                  title: 'Wizard hit an error',
                  detail: (latestSession.error as { message?: string } | null)?.message ?? null,
              }
            : null

    // A session exists past the early return above, so this is always a current run.
    return { phase, steps, error, prUrl: null, isCurrent: true }
}

/**
 * The Installation layer: one normalized `InstallationProgress` the UI renders, hiding which underlying
 * stream(s) feed it.
 *   - `mode: 'local'` — the wizard session stream only (the local CLI is the writer).
 *   - `mode: 'cloud'` — the TaskRun pipeline (provision → clone → wizard → agent → PR, plus terminal
 *     status, PR url, error) merged with the wizard session stream (wizard-stage detail).
 *
 * Both sources are always connected; in local mode the task source is a no-op (empty runId), so the
 * merge selector can reference its values unconditionally and just branch on `mode`.
 */
export const installationProgressLogic = kea<installationProgressLogicType>([
    props({} as InstallationProgressLogicProps),
    key((props) => (props.mode === 'cloud' ? `cloud:${props.runId ?? ''}` : 'local')),
    path((key) => ['scenes', 'onboarding', 'installationProgressLogic', key]),
    connect((props: InstallationProgressLogicProps) => ({
        values: [
            taskRunStreamLogic({ runId: props.runId ?? '', taskId: props.taskId ?? '' }),
            ['taskRunState', 'progressSteps', 'connectionStatus as taskConnectionStatus', 'isComplete', 'isStalled'],
            wizardSessionStreamLogic({ workflowId: WORKFLOW_ID }),
            ['latestSession', 'connectionStatus as sessionConnectionStatus'],
        ],
        actions: [
            taskRunStreamLogic({ runId: props.runId ?? '', taskId: props.taskId ?? '' }),
            ['connect as connectTaskRun', 'disconnect as disconnectTaskRun'],
            wizardSessionStreamLogic({ workflowId: WORKFLOW_ID }),
            ['connect as connectSession', 'disconnect as disconnectSession'],
        ],
    })),
    selectors({
        installationProgress: [
            (s) => [
                s.taskRunState,
                s.progressSteps,
                s.taskConnectionStatus,
                s.latestSession,
                s.sessionConnectionStatus,
                s.isStalled,
                (_, props) => props.mode,
            ],
            (
                taskRunState,
                progressSteps,
                taskConnectionStatus,
                latestSession,
                sessionConnectionStatus,
                isStalled,
                mode
            ): InstallationProgress =>
                mode === 'cloud'
                    ? cloudProgress(taskRunState, progressSteps, taskConnectionStatus, latestSession, isStalled)
                    : localProgress(latestSession, sessionConnectionStatus),
        ],
    }),
    afterMount(({ actions }) => {
        actions.connectTaskRun()
        actions.connectSession()
    }),
    beforeUnmount(({ actions }) => {
        actions.disconnectTaskRun()
        actions.disconnectSession()
    }),
])
