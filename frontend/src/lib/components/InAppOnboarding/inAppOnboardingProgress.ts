import { InAppOnboardingFlow, InAppOnboardingSignal } from './inAppOnboardingFlows'

export interface InAppOnboardingProgress {
    stepIndex: number
    count: number
}

export const INITIAL_PROGRESS: InAppOnboardingProgress = { stepIndex: 0, count: 0 }

export function isFlowComplete(flow: InAppOnboardingFlow, progress: InAppOnboardingProgress): boolean {
    return progress.stepIndex >= flow.steps.length
}

export function advanceProgress(
    flow: InAppOnboardingFlow,
    progress: InAppOnboardingProgress,
    signal: InAppOnboardingSignal
): InAppOnboardingProgress {
    const step = flow.steps[progress.stepIndex]
    if (!step || step.signal !== signal) {
        return progress
    }
    const count = progress.count + 1
    return count >= step.times ? { stepIndex: progress.stepIndex + 1, count: 0 } : { ...progress, count }
}
