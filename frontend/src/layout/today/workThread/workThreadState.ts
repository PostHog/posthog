import type {
    WorkLineApi,
    WorkOptionApi,
    WorkStepApi,
    WorkThreadApi,
} from 'products/today/frontend/generated/api.schemas'

import type { WorkStepState } from './workThreadTypes'

export interface WorkThreadSummary {
    steps: number
    inOrder: number
    alongside: number
    needsYou: number
    waiting: number
    done: number
}

export function workLines(line: WorkLineApi): WorkLineApi[] {
    return [line, ...line.steps.flatMap((step) => step.alongside.flatMap(workLines))]
}

/** Step keys are unique in a thread, alongside lines included, so a key names one step. */
export function workStepByKey(thread: WorkThreadApi, stepKey: string): WorkStepApi | null {
    return (
        workLines(thread.line)
            .flatMap((line) => line.steps)
            .find((step) => step.key === stepKey) ?? null
    )
}

function isLastStep(line: WorkLineApi, step: WorkStepApi): boolean {
    return line.steps[line.steps.length - 1]?.key === step.key
}

function nextOptions(step: WorkStepApi): WorkOptionApi[] {
    return step.options.filter((option) => option.kind === 'next')
}

export function workStepState(line: WorkLineApi, step: WorkStepApi): WorkStepState {
    const next = nextOptions(step)
    if (!isLastStep(line, step) || next.length === 0) {
        return 'done'
    }
    return next.every((option) => option.gate) ? 'waiting' : 'needs_you'
}

export function isWorkStepExpanded(state: WorkStepState, override: boolean | undefined): boolean {
    return override ?? state !== 'done'
}

export function workThreadSummary(thread: WorkThreadApi): WorkThreadSummary {
    const lines = workLines(thread.line)
    const summary: WorkThreadSummary = {
        steps: 0,
        inOrder: thread.line.steps.length,
        alongside: lines.length - 1,
        needsYou: 0,
        waiting: 0,
        done: 0,
    }
    for (const line of lines) {
        for (const step of line.steps) {
            summary.steps += 1
            const state = workStepState(line, step)
            if (state === 'needs_you') {
                summary.needsYou += 1
            } else if (state === 'waiting') {
                summary.waiting += 1
            } else {
                summary.done += 1
            }
        }
    }
    return summary
}

export function nextWorkOption(thread: WorkThreadApi): { step: WorkStepApi; option: WorkOptionApi } | null {
    for (const line of workLines(thread.line)) {
        const step = line.steps[line.steps.length - 1]
        if (!step || workStepState(line, step) !== 'needs_you') {
            continue
        }
        const option = nextOptions(step).find((candidate) => !candidate.gate)
        if (option) {
            return { step, option }
        }
    }
    return null
}
