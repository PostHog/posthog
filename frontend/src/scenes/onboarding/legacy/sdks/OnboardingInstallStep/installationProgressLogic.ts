import { afterMount, beforeUnmount, connect, kea, key, path, props, selectors } from 'kea'

import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

import { taskRunStreamLogic, TaskRunStreamState } from './taskRunStreamLogic'
import type { installationProgressLogicType } from './installationProgressLogicType'

// The wizard session stream the local CLI publishes to — and the channel a cloud wizard reports its
// own sub-progress on. Matches wizardProgressTrackerLogic's WORKFLOW_ID.
const WORKFLOW_ID = 'posthog-integration'

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
    runId: string
    taskId: string
}

const STEP_STATUSES: Record<string, InstallationStepStatus> = {
    pending: 'pending',
    in_progress: 'in_progress',
    completed: 'completed',
    failed: 'failed',
}

function stepStatus(raw: string): InstallationStepStatus {
    return STEP_STATUSES[raw] ?? 'pending'
}

function phaseFromTaskRun(state: TaskRunStreamState | null, connecting: boolean): InstallationPhase {
    if (!state) {
        return connecting ? 'connecting' : 'idle'
    }
    switch (state.status) {
        case 'completed':
            return 'completed'
        case 'failed':
        case 'cancelled':
            return 'error'
        default:
            return 'running'
    }
}

/**
 * The Installation layer: one normalized `InstallationProgress` the UI renders, hiding which underlying
 * stream(s) feed it. For a cloud run it merges the TaskRun pipeline (the spine — provision → clone →
 * wizard → agent → PR, plus terminal status, PR url, and error) with the wizard session stream (the
 * fine-grained detail for the wizard stage, when the cloud wizard reports one).
 *
 * Phase A is cloud-only (keyed by runId, both sources connected). Local mode (wizard session only) is a
 * follow-up that points the existing tracker/FAB at this same layer.
 */
export const installationProgressLogic = kea<installationProgressLogicType>([
    props({} as InstallationProgressLogicProps),
    key((props) => props.runId),
    path((key) => ['scenes', 'onboarding', 'installationProgressLogic', key]),
    connect((props: InstallationProgressLogicProps) => ({
        values: [
            taskRunStreamLogic({ runId: props.runId, taskId: props.taskId }),
            ['taskRunState', 'progressSteps', 'connectionStatus as taskConnectionStatus', 'isComplete'],
            wizardSessionStreamLogic({ workflowId: WORKFLOW_ID }),
            ['latestSession'],
        ],
        actions: [
            taskRunStreamLogic({ runId: props.runId, taskId: props.taskId }),
            ['connect as connectTaskRun', 'disconnect as disconnectTaskRun'],
            wizardSessionStreamLogic({ workflowId: WORKFLOW_ID }),
            ['connect as connectSession', 'disconnect as disconnectSession'],
        ],
    })),
    selectors({
        installationProgress: [
            (s) => [s.taskRunState, s.progressSteps, s.taskConnectionStatus, s.latestSession],
            (taskRunState, progressSteps, taskConnectionStatus, latestSession): InstallationProgress => {
                const phase = phaseFromTaskRun(taskRunState, taskConnectionStatus === 'connecting')

                // The wizard session enriches the wizard stage with its live sub-task. Absent today (the
                // cloud wizard doesn't report a session yet), so this degrades to the bare TaskRun step.
                const wizardDetail =
                    latestSession?.tasks?.find((t) => t.status === 'in_progress')?.title ??
                    (latestSession?.run_phase === 'error' ? 'Wizard hit an error' : null)

                const steps: InstallationStep[] = progressSteps.map((p) => ({
                    id: `${p.group}:${p.step}`,
                    label: p.label,
                    status: stepStatus(p.status),
                    detail: p.step === 'wizard' && p.status === 'in_progress' ? wizardDetail : p.detail,
                }))

                const error =
                    phase === 'error'
                        ? {
                              title: 'Installation failed',
                              detail:
                                  taskRunState?.error_message ??
                                  (latestSession?.error as { message?: string } | null)?.message ??
                                  null,
                          }
                        : null

                return {
                    phase,
                    steps,
                    error,
                    prUrl: taskRunState?.output?.pr_url ?? null,
                    isCurrent: phase !== 'idle',
                }
            },
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
