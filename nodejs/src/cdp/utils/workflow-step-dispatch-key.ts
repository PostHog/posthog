import { CyclotronJobInvocationHogFunction } from '../types'

// A run that dispatches an external job (an AI task, a scout run) parks until Django wakes it by this
// key. `actionStepCount` holds across a retry of the same step and changes on a loop revisit, so a
// retry replays the same dispatch while a revisit gets a fresh one and a stale wake cannot advance it.
export const buildWorkflowStepDispatchKey = (jobId: string, actionId: string, actionStepCount: number): string =>
    `${jobId}:${actionId}:${actionStepCount}`

export const parseWorkflowStepDispatchKey = (key: string): { jobId: string; actionId: string } | null => {
    const parts = key.split(':')
    if (parts.length < 3 || !parts[0]) {
        return null
    }
    // Action ids are free-form and may contain ':'; the job id and step count never do.
    return { jobId: parts[0], actionId: parts.slice(1, -1).join(':') }
}

export const workflowStepDispatchKeyFromInvocation = (invocation: CyclotronJobInvocationHogFunction): string | null => {
    const { actionId, actionStepCount } = invocation.state
    if (!actionId || actionStepCount === undefined) {
        return null
    }
    return buildWorkflowStepDispatchKey(invocation.id, actionId, actionStepCount)
}
