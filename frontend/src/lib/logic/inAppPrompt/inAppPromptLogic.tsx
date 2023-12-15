import { Placement } from '@floating-ui/react'
import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { now } from 'lib/dayjs'
import {
    IconApps,
    IconBarChart,
    IconCoffee,
    IconCohort,
    IconComment,
    IconExperiment,
    IconFlag,
    IconGauge,
    IconLive,
    IconMessages,
    IconPerson,
    IconRecording,
    IconTools,
    IconTrendUp,
    IconUnverifiedEvent,
} from 'lib/lemon-ui/icons'
import {
    LemonActionableTooltip,
    LemonActionableTooltipProps,
} from 'lib/lemon-ui/LemonActionableTooltip/LemonActionableTooltip'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { createRoot } from 'react-dom/client'
import wcmatch from 'wildcard-match'

import { inAppPromptEventCaptureLogic } from './inAppPromptEventCaptureLogic'
import type { inAppPromptLogicType } from './inAppPromptLogicType'

/** To be extended with other types of notifications e.g. modals, bars */
export type PromptType = 'tooltip'

export type PromptButton = {
    url?: string
    action?: string
    label: string
}

export type Prompt = {
    step: number
    type: PromptType
    text: string
    placement: Placement
    reference: string | null
    title?: string
    buttons?: PromptButton[]
    icon?: string
}

export type Tooltip = Prompt & { type: 'tooltip' }

export type PromptSequence = {
    key: string
    prompts: Prompt[]
    path_match: string[]
    path_exclude: string[]
    must_be_completed?: string[]
    requires_opt_in?: boolean
    type: string
}

export type PromptConfig = {
    sequences: PromptSequence[]
}

export type PromptState = {
    key: string
    last_updated_at: string
    step: number | null
    completed?: boolean
    dismissed?: boolean
}

export type ValidSequenceWithState = {
    sequence: PromptSequence
    state: { step: number; completed?: boolean }
}

export type PromptUserState = {
    [key: string]: PromptState
}

export enum DefaultAction {
    NEXT = 'next',
    PREVIOUS = 'previous',
    START_PRODUCT_TOUR = 'start-product-tour',
    SKIP = 'skip',
}

// we show a new sequence with 1 second delay, because users immediately dismiss prompts that are invasive
const NEW_SEQUENCE_DELAY = 1000
// make sure to change this prefix in case the schema of cached values is changed
// otherwise the code will try to run with cached deprecated values
const CACHE_PREFIX = 'v5'

const iconMap = {
    home: <Lettermark name="PostHog" />,
    'live-events': <IconLive />,
    dashboard: <IconGauge />,
    insight: <IconBarChart />,
    messages: <IconMessages />,
    recordings: <IconRecording />,
    'feature-flags': <IconFlag />,
    experiments: <IconExperiment />,
    'web-performance': <IconCoffee />,
    'data-management': <IconUnverifiedEvent />,
    persons: <IconPerson />,
    cohorts: <IconCohort />,
    annotations: <IconComment />,
    apps: <IconApps />,
    toolbar: <IconTools />,
    'trend-up': <IconTrendUp />,
}

/** Display a <LemonActionableTooltip> with the ability to remove it from the DOM */
function cancellableTooltipWithRetries(
    tooltip: Tooltip,
    onAction: (action: string) => void,
    options: { maxSteps: number; onClose: () => void; next: () => void; previous: () => void }
): { close: () => void; show: Promise<unknown> } {
    let trigger = (): void => {}
    const close = (): number => window.setTimeout(trigger, 1)
    const show = new Promise((resolve, reject) => {
        const div = document.createElement('div')
        const root = createRoot(div)
        function destroy(): void {
            root.unmount()
            if (div.parentNode) {
                div.parentNode.removeChild(div)
            }
        }

        document.body.appendChild(div)
        trigger = destroy

        const tryRender = function (retries: number): void {
            try {
                let props: LemonActionableTooltipProps = {
                    title: tooltip.title,
                    text: tooltip.text,
                    placement: tooltip.placement,
                    step: tooltip.step,
                    maxSteps: options.maxSteps,
                    next: () => {
                        destroy()
                        options.next()
                    },
                    previous: () => {
                        destroy()
                        options.previous()
                    },
                    close: () => {
                        destroy()
                        options.onClose()
                    },
                    visible: true,
                    buttons: tooltip.buttons
                        ? tooltip.buttons.map((button) => {
                              if (button.action) {
                                  return {
                                      ...button,
                                      action: () => onAction(button.action as string),
                                  }
                              }
                              return {
                                  url: button.url,
                                  label: button.label,
                              }
                          })
                        : [],
                    icon: tooltip.icon ? iconMap[tooltip.icon] : null,
                }
                if (tooltip.reference) {
                    const element = tooltip.reference
                        ? (document.querySelector(`[data-attr="${tooltip.reference}"]`) as HTMLElement)
                        : null
                    if (!element) {
                        throw 'Prompt reference element not found'
                    }
                    props = { ...props, element }
                }

                root.render(<LemonActionableTooltip {...props} />)

                resolve(true)
            } catch (e) {
                if (retries == 0) {
                    reject(e)
                } else {
                    setTimeout(function () {
                        tryRender(retries - 1)
                    }, 1000)
                }
            }
        }
        tryRender(3)
    })

    return {
        close,
        show,
    }
}

export const inAppPromptLogic = kea<inAppPromptLogicType>([
    path(['lib', 'logic', 'inAppPrompt']),
    connect(inAppPromptEventCaptureLogic),
    actions({
        findValidSequences: true,
        setValidSequences: (validSequences: ValidSequenceWithState[]) => ({ validSequences }),
        runFirstValidSequence: (options: { runDismissedOrCompleted?: boolean }) => ({ options }),
        runSequence: (sequence: PromptSequence, step: number) => ({ sequence, step }),
        promptShownSuccessfully: true,
        closePrompts: true,
        dismissSequence: true,
        clearSequence: true,
        nextPrompt: true,
        previousPrompt: true,
        updatePromptState: (update: Partial<PromptState>) => ({ update }),
        setUserState: (state: PromptUserState, sync = true) => ({ state, sync }),
        syncState: (options: { forceRun?: boolean }) => ({ options }),
        setSequences: (sequences: PromptSequence[]) => ({ sequences }),
        promptAction: (action: string) => ({ action }),
        optInProductTour: true,
        optOutProductTour: true,
    }),
    reducers(() => ({
        sequences: [
            [] as PromptSequence[],
            { persist: true, prefix: CACHE_PREFIX },
            {
                setSequences: (_, { sequences }) => sequences,
            },
        ],
        currentSequence: [
            null as PromptSequence | null,
            {
                runSequence: (_, { sequence }) => sequence,
                clearSequence: () => null,
            },
        ],
        currentStep: [
            0,
            {
                runSequence: (_, { step }) => step,
                clearSequence: () => 0,
            },
        ],
        userState: [
            {} as PromptUserState,
            { persist: true, prefix: CACHE_PREFIX },
            {
                setUserState: (_, { state }) => state,
            },
        ],
        canShowProductTour: [
            false,
            { persist: true, prefix: CACHE_PREFIX },
            {
                optInProductTour: () => true,
                optOutProductTour: () => false,
            },
        ],
        validSequences: [
            [] as ValidSequenceWithState[],
            {
                setValidSequences: (_, { validSequences }) => validSequences,
            },
        ],
        validProductTourSequences: [
            [] as ValidSequenceWithState[],
            {
                setValidSequences: (_, { validSequences }) =>
                    validSequences?.filter((v) => v.sequence.type === 'product-tour') || [],
            },
        ],
        isPromptVisible: [
            false,
            {
                promptShownSuccessfully: () => true,
                closePrompts: () => false,
                dismissSequence: () => false,
            },
        ],
    })),
    selectors(() => ({
        prompts: [(s) => [s.currentSequence], (sequence: PromptSequence | null) => sequence?.prompts ?? []],
        sequenceKey: [(s) => [s.currentSequence], (sequence: PromptSequence | null) => sequence?.key],
    })),
    listeners(({ actions, values, cache }) => ({
        syncState: async ({ options }, breakpoint) => {
            await breakpoint(100)
            try {
                const updatedState = await api.update(`api/prompts/my_prompts`, values.userState)
                if (updatedState) {
                    if (JSON.stringify(values.userState) !== JSON.stringify(updatedState['state'])) {
                        actions.setUserState(updatedState['state'], false)
                    }
                    if (
                        JSON.stringify(values.sequences) !== JSON.stringify(updatedState['sequences']) ||
                        options.forceRun
                    ) {
                        actions.setSequences(updatedState['sequences'])
                    }
                }
            } catch (error: any) {
                console.error(error)
            }
        },
        closePrompts: () => cache.runOnClose?.(),
        setSequences: actions.findValidSequences,
        runSequence: async ({ sequence, step = 0 }) => {
            const prompt = sequence.prompts.find((prompt) => prompt.step === step)
            if (prompt) {
                switch (prompt.type) {
                    case 'tooltip': {
                        const { close, show } = cancellableTooltipWithRetries(prompt, actions.promptAction, {
                            maxSteps: values.prompts.length,
                            onClose: actions.dismissSequence,
                            previous: () => actions.promptAction(DefaultAction.PREVIOUS),
                            next: () => actions.promptAction(DefaultAction.NEXT),
                        })
                        cache.runOnClose = close

                        try {
                            await show
                            const updatedState: Partial<PromptState> = {
                                step: values.currentStep,
                            }
                            if (step === sequence.prompts.length - 1) {
                                updatedState.completed = true
                                inAppPromptEventCaptureLogic.actions.reportPromptSequenceCompleted(
                                    sequence.key,
                                    step,
                                    values.prompts.length
                                )
                            }
                            actions.updatePromptState(updatedState)
                            inAppPromptEventCaptureLogic.actions.reportPromptShown(
                                prompt.type,
                                sequence.key,
                                step,
                                values.prompts.length
                            )
                            actions.promptShownSuccessfully()
                        } catch (e) {
                            console.error(e)
                        }
                        break
                    }
                    default:
                        break
                }
            }
        },
        updatePromptState: ({ update }) => {
            if (values.sequenceKey) {
                const key = values.sequenceKey
                const currentState = values.userState[key] || { key, step: 0 }
                actions.setUserState({
                    ...values.userState,
                    [key]: {
                        ...currentState,
                        ...update,
                        last_updated_at: now().toISOString(),
                    },
                })
            }
        },
        previousPrompt: () => {
            if (values.currentSequence) {
                actions.runSequence(values.currentSequence, values.currentStep - 1)
                inAppPromptEventCaptureLogic.actions.reportPromptBackward(
                    values.currentSequence.key,
                    values.currentStep,
                    values.currentSequence.prompts.length
                )
            }
        },
        nextPrompt: () => {
            if (values.currentSequence) {
                actions.runSequence(values.currentSequence, values.currentStep + 1)
                inAppPromptEventCaptureLogic.actions.reportPromptForward(
                    values.currentSequence.key,
                    values.currentStep,
                    values.currentSequence.prompts.length
                )
            }
        },
        findValidSequences: () => {
            const pathname = router.values.currentLocation.pathname
            const valid = []
            for (const sequence of values.sequences) {
                // for now the only valid rule is related to the pathname, can be extended
                const must_match = [...sequence.path_match]
                if (must_match.includes('/*')) {
                    must_match.push('/**')
                }
                const isMatchingPath = must_match.some((value) => wcmatch(value)(pathname))
                if (!isMatchingPath) {
                    continue
                }
                const isMatchingExclusion = sequence.path_exclude.some((value) => wcmatch(value)(pathname))
                if (isMatchingExclusion) {
                    continue
                }
                const hasOptedInToSequence = sequence.requires_opt_in ? values.canShowProductTour : true
                if (!values.userState[sequence.key]) {
                    continue
                }
                const sequenceState = values.userState[sequence.key]
                const completed = !!sequenceState.completed || sequenceState.step === sequence.prompts.length
                const canRun = !sequenceState.dismissed && hasOptedInToSequence
                if (!canRun) {
                    continue
                }
                if (sequence.type !== 'product-tour' && (completed || sequenceState.step === sequence.prompts.length)) {
                    continue
                }
                valid.push({
                    sequence,
                    state: {
                        step: sequenceState.step ? sequenceState.step + 1 : 0,
                        completed,
                    },
                })
            }
            actions.setValidSequences(valid)
        },
        setValidSequences: () => {
            if (!values.isPromptVisible) {
                actions.runFirstValidSequence({})
            }
        },
        runFirstValidSequence: ({ options }) => {
            if (values.validSequences) {
                actions.closePrompts()
                let firstValid = null
                if (options.runDismissedOrCompleted) {
                    firstValid = values.validSequences[0]
                } else {
                    // to make it less greedy, we don't allow half-run sequences to be started automatically
                    firstValid = values.validSequences.filter(
                        (sequence) => !sequence.state.completed && sequence.state.step === 0
                    )?.[0]
                }
                if (firstValid) {
                    const { sequence, state } = firstValid
                    setTimeout(() => actions.runSequence(sequence, state.step), NEW_SEQUENCE_DELAY)
                }
            }
        },
        dismissSequence: () => {
            if (values.sequenceKey) {
                const key = values.sequenceKey
                const currentState = values.userState[key]
                if (currentState && !currentState.completed) {
                    actions.updatePromptState({
                        dismissed: true,
                    })
                    if (values.currentStep < values.prompts.length) {
                        inAppPromptEventCaptureLogic.actions.reportPromptSequenceDismissed(
                            values.sequenceKey,
                            values.currentStep,
                            values.prompts.length
                        )
                    }
                }
                actions.clearSequence()
            }
        },
        setUserState: ({ sync }) => sync && actions.syncState({}),
        promptAction: ({ action }) => {
            actions.closePrompts()
            switch (action) {
                case DefaultAction.NEXT:
                    actions.nextPrompt()
                    break
                case DefaultAction.PREVIOUS:
                    actions.previousPrompt()
                    break
                case DefaultAction.START_PRODUCT_TOUR:
                    actions.optInProductTour()
                    inAppPromptEventCaptureLogic.actions.reportProductTourStarted()
                    actions.runFirstValidSequence({ runDismissedOrCompleted: true })
                    break
                case DefaultAction.SKIP:
                    actions.optOutProductTour()
                    inAppPromptEventCaptureLogic.actions.reportProductTourSkipped()
                    break
                default: {
                    const potentialSequence = values.sequences.find((s) => s.key === action)
                    if (potentialSequence) {
                        actions.runSequence(potentialSequence, 0)
                    }
                    break
                }
            }
        },
    })),
    urlToAction(({ actions }) => ({
        '*': () => {
            actions.closePrompts()
            if (!['login', 'signup', 'ingestion'].find((path) => router.values.location.pathname.includes(path))) {
                actions.findValidSequences()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.syncState({ forceRun: true })
    }),
    beforeUnmount(({ cache }) => cache.runOnClose?.()),
])
