import { CyclotronJobInvocationHogFunction } from '../types'

// Step count is the nonce: a retry replays the same key, a loop revisit gets a fresh one.
export const buildWorkflowStepDispatchKey = (jobId: string, actionId: string, actionStepCount: number): string =>
    `${jobId}:${actionId}:${actionStepCount}`

export const parseWorkflowStepDispatchKey = (key: string): { jobId: string; actionId: string } | null => {
    const parts = key.split(':')
    if (parts.length < 3 || !parts[0]) {
        return null
    }
    return { jobId: parts[0], actionId: parts.slice(1, -1).join(':') }
}

export const workflowStepDispatchKeyFromInvocation = (invocation: CyclotronJobInvocationHogFunction): string | null => {
    const { actionId, actionStepCount } = invocation.state
    if (!actionId || actionStepCount === undefined) {
        return null
    }
    return buildWorkflowStepDispatchKey(invocation.id, actionId, actionStepCount)
}
