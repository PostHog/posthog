import { CyclotronJobInvocationHogFunction } from '../types'

export const buildWorkflowStepDispatchKey = (
    jobId: string,
    actionId: string,
    actionStepCount: number,
    rerunAttempts = 0
): string => `${jobId}:${actionId}:${actionStepCount}${rerunAttempts > 0 ? `.r${rerunAttempts}` : ''}`

export const parseWorkflowStepDispatchKey = (key: string): { jobId: string; actionId: string } | null => {
    const parts = key.split(':')
    const step = /^(0|[1-9]\d*)(?:\.r([1-9]\d*))?$/.exec(parts[parts.length - 1])
    const actionId = parts.slice(1, -1).join(':')
    if (
        parts.length < 3 ||
        !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(parts[0]) ||
        !actionId.trim() ||
        !step ||
        !Number.isSafeInteger(Number(step[1])) ||
        (step[2] !== undefined && !Number.isSafeInteger(Number(step[2])))
    ) {
        return null
    }
    return { jobId: parts[0].toLowerCase(), actionId }
}

export const workflowStepDispatchKeyFromInvocation = (invocation: CyclotronJobInvocationHogFunction): string | null => {
    const { actionId, actionStepCount } = invocation.state
    if (!actionId || actionStepCount === undefined) {
        return null
    }
    return buildWorkflowStepDispatchKey(invocation.id, actionId, actionStepCount, invocation.state.rerunAttempts)
}
