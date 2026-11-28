import posthog from 'posthog-js'

import type {
    WorkItemApi,
    WorkOptionApi,
    WorkStepApi,
    WorkThreadApi,
} from 'products/today/frontend/generated/api.schemas'

// pinned: analytics event names. Renaming one breaks the dashboards and insights built on it.
const WORK_THREAD_EVENTS = {
    stepToggled: 'work thread step toggled',
    optionOpened: 'work thread option opened',
    optionDismissed: 'work thread option dismissed',
    optionRun: 'work thread option run',
    promptShown: 'work thread prompt shown',
    promptCopied: 'work thread prompt copied',
    itemViewed: 'work thread item viewed',
    itemOpened: 'work thread item opened',
} as const

function optionProperties(thread: WorkThreadApi, step: WorkStepApi, option: WorkOptionApi): Record<string, unknown> {
    return {
        thread_key: thread.key,
        step_key: step.key,
        option_key: option.key,
        option_kind: option.kind,
        helper_mode: option.helper.mode,
        helper_product: option.helper.product,
    }
}

function itemProperties(thread: WorkThreadApi, item: WorkItemApi): Record<string, unknown> {
    return { thread_key: thread.key, item_type: item.type, item_product: item.product }
}

export function captureWorkStepToggled(thread: WorkThreadApi, step: WorkStepApi, expanded: boolean): void {
    posthog.capture(WORK_THREAD_EVENTS.stepToggled, { thread_key: thread.key, step_key: step.key, expanded })
}

export function captureWorkOptionOpened(thread: WorkThreadApi, step: WorkStepApi, option: WorkOptionApi): void {
    posthog.capture(WORK_THREAD_EVENTS.optionOpened, optionProperties(thread, step, option))
}

export function captureWorkOptionDismissed(
    thread: WorkThreadApi,
    step: WorkStepApi,
    option: WorkOptionApi,
    promptShown: boolean
): void {
    posthog.capture(WORK_THREAD_EVENTS.optionDismissed, {
        ...optionProperties(thread, step, option),
        prompt_shown: promptShown,
    })
}

export function captureWorkOptionRun(thread: WorkThreadApi, step: WorkStepApi, option: WorkOptionApi): void {
    posthog.capture(WORK_THREAD_EVENTS.optionRun, {
        ...optionProperties(thread, step, option),
        run_type: option.helper.run.type,
    })
}

export function captureWorkPromptShown(thread: WorkThreadApi, step: WorkStepApi, option: WorkOptionApi): void {
    posthog.capture(WORK_THREAD_EVENTS.promptShown, optionProperties(thread, step, option))
}

export function captureWorkPromptCopied(
    thread: WorkThreadApi,
    step: WorkStepApi,
    option: WorkOptionApi,
    method: 'clipboard' | 'selected'
): void {
    posthog.capture(WORK_THREAD_EVENTS.promptCopied, { ...optionProperties(thread, step, option), method })
}

export function captureWorkItemViewed(thread: WorkThreadApi, item: WorkItemApi): void {
    posthog.capture(WORK_THREAD_EVENTS.itemViewed, itemProperties(thread, item))
}

export function captureWorkItemOpened(thread: WorkThreadApi, item: WorkItemApi): void {
    posthog.capture(WORK_THREAD_EVENTS.itemOpened, itemProperties(thread, item))
}
