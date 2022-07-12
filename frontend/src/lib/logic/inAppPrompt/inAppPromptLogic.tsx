import React from 'react'
import ReactDOM from 'react-dom'
import { Placement } from '@floating-ui/react-dom-interactions'
import { kea, path, actions, reducers, listeners, events, selectors, connect } from 'kea'
import type { inAppPromptLogicType } from './inAppPromptLogicType'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import {
    LemonActionableTooltip,
    LemonActionableTooltipProps,
} from 'lib/components/LemonActionableTooltip/LemonActionableTooltip'
import { inAppPromptEventCaptureLogic } from './inAppPromptEventCaptureLogic'
import { featureFlagLogic } from '../featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

/** To be extended with other types of notifications e.g. modals, bars */
export type PromptType = 'tooltip'

export type Prompt = {
    step: number // starting from 1, so that tracking prompts events is human readable (e.g. step 1 out of 3)
    type: PromptType
    text: string
    placement: Placement
    reference: string
}

export type Tooltip = Prompt & { type: 'tooltip' }

export type PromptRule = {
    path: string
}

export type PromptSequence = {
    key: string
    prompts: Prompt[]
    rule: PromptRule
    oneTimeOnly: boolean
}

export type PromptConfig = {
    sequences: PromptSequence[]
}

export type PromptUserState = {
    [key: string]: {
        step: number
        completed?: boolean
        dismissed?: boolean
    }
}

function cancellableTooltipWithRetries(
    tooltip: Tooltip,
    config: { maxSteps: number; onClose: () => void; next: () => void; previous: () => void }
): { close: () => void; show: Promise<unknown> } {
    let trigger = (): void => {}
    const close = (): number => window.setTimeout(trigger, 1)
    const show = new Promise((resolve, reject) => {
        const div = document.createElement('div')
        function destroy(): void {
            const unmountResult = ReactDOM.unmountComponentAtNode(div)
            if (unmountResult && div.parentNode) {
                div.parentNode.removeChild(div)
            }
        }

        document.body.appendChild(div)
        trigger = destroy

        const tryRender = function (retries: number): void {
            try {
                const element = document.querySelector(`[data-tooltip="${tooltip.reference}"]`) as HTMLElement
                if (!element) {
                    throw 'element not found'
                }
                const props: LemonActionableTooltipProps = {
                    element,
                    text: tooltip.text,
                    placement: tooltip.placement,
                    step: tooltip.step - 1,
                    maxSteps: config.maxSteps,
                    next: () => {
                        destroy()
                        config.next()
                    },
                    previous: () => {
                        destroy()
                        config.previous()
                    },
                    close: () => {
                        destroy()
                        config.onClose()
                    },
                    visible: true,
                }

                ReactDOM.render(<LemonActionableTooltip {...props} />, div)

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

const experimentTooltipsConfig: PromptConfig = {
    sequences: [
        {
            key: 'experiment-tooltip',
            prompts: [
                {
                    step: 1,
                    type: 'tooltip',
                    text: 'Hey welcome to the magical world of PostHog, where your analytics dreams come true.',
                    placement: 'bottom-end',
                    reference: 'experiment-tooltip-0',
                },
                {
                    step: 2,
                    type: 'tooltip',
                    text: 'This is a second tooltip',
                    placement: 'top-end',
                    reference: 'experiment-tooltip-1',
                },
            ],
            rule: {
                path: '/events',
            },
            oneTimeOnly: false,
        },
    ],
}

export const inAppPromptLogic = kea<inAppPromptLogicType>([
    path(['lib', 'logic', 'inAppPrompt']),
    connect([inAppPromptEventCaptureLogic]),
    actions({
        tooltip: (tooltip: Tooltip) => ({ tooltip }),
        setConfig: (config: PromptConfig) => ({ config }),
        runFirstValidSequence: (opts: { runDismissedOrCompleted?: boolean; restart?: boolean }) => opts,
        runSequence: (sequence: PromptSequence, step: number) => ({ sequence, step }),
        dismissSequence: true,
        clearSequence: true,
        nextPrompt: true,
        previousPrompt: true,
        updateUserState: true,
        setUserState: (state: PromptUserState) => ({ state }),
    }),
    reducers(() => ({
        config: [
            null as PromptConfig | null,
            { persist: true },
            {
                setConfig: (_, { config }) => config,
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
            1,
            {
                runSequence: (_, { step }) => step,
                clearSequence: () => 1,
            },
        ],
        userState: [
            {} as PromptUserState,
            { persist: true },
            {
                setUserState: (_, { state }) => state,
            },
        ],
    })),
    selectors(() => ({
        prompts: [(s) => [s.currentSequence], (sequence: PromptSequence | null) => sequence?.prompts ?? []],
        sequenceKey: [(s) => [s.currentSequence], (sequence: PromptSequence | null) => sequence?.key],
        validSequences: [
            (s) => [s.config, s.userState, router.selectors.currentLocation],
            (config: PromptConfig | null, userState: PromptUserState, currentLocation: { pathname: string }) => {
                const pathname = currentLocation.pathname
                const valid = []
                if (!config) {
                    return []
                }
                for (const sequence of config.sequences) {
                    // for now the only valid rule is related to the pathname, can be extended
                    if (sequence.rule.path === pathname) {
                        if (userState[sequence.key]) {
                            const sequenceState = userState[sequence.key]
                            const completed = sequenceState.step === sequence.prompts.length
                            const dismissed = !!sequenceState.dismissed
                            if (sequence.oneTimeOnly && (completed || dismissed)) {
                                continue
                            }
                            valid.push({
                                sequence,
                                step: sequenceState.step,
                                completed,
                                dismissed,
                            })
                        } else {
                            valid.push({ sequence, step: 0 })
                        }
                    }
                }
                return valid
            },
        ],
    })),
    listeners(({ actions, values, cache }) => ({
        setConfig: () => actions.runFirstValidSequence({}),
        runSequence: ({ sequence, step = 1 }) => {
            const prompt = sequence.prompts.find((prompt) => prompt.step === step)
            if (prompt) {
                switch (prompt.type) {
                    case 'tooltip':
                        actions.tooltip(prompt)
                        break
                    default:
                        break
                }
            }
        },
        tooltip: async ({ tooltip }) => {
            const { close, show } = cancellableTooltipWithRetries(tooltip, {
                maxSteps: values.prompts.length,
                onClose: () => {
                    actions.dismissSequence()
                },
                previous: actions.previousPrompt,
                next: actions.nextPrompt,
            })
            cache.runOnClose = close

            show.then(() => {
                actions.updateUserState()
            }).catch((err) => console.error(err))
        },
        updateUserState: () => {
            // TODO sync this with backend
            if (values.sequenceKey) {
                const key = values.sequenceKey
                const currentState = values.userState[key]
                if (currentState && currentState.step < values.currentStep) {
                    actions.setUserState({
                        ...values.userState,
                        [key]: {
                            ...currentState,
                            step: values.currentStep,
                        },
                    })
                } else {
                    actions.setUserState({
                        ...values.userState,
                        [key]: {
                            step: values.currentStep,
                        },
                    })
                }
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
                if (values.currentStep === values.currentSequence.prompts.length) {
                    inAppPromptEventCaptureLogic.actions.reportPromptSequenceCompleted(
                        values.currentSequence.key,
                        values.currentStep,
                        values.prompts.length
                    )
                }
            }
        },
        runFirstValidSequence: (opts) => {
            if (values.validSequences) {
                let firstValid = null
                if (opts.runDismissedOrCompleted) {
                    firstValid = values.validSequences[0]
                } else {
                    firstValid = values.validSequences.filter(
                        (sequence) => !sequence.completed || !sequence.dismissed
                    )?.[0]
                    console.log(firstValid)
                }
                if (firstValid) {
                    const { sequence, step } = firstValid
                    actions.runSequence(sequence, opts.restart ? 1 : step)
                }
            }
        },
        dismissSequence: () => {
            if (values.sequenceKey) {
                const key = values.sequenceKey
                const currentState = values.userState[key]
                if (currentState) {
                    actions.setUserState({
                        ...values.userState,
                        [key]: {
                            ...currentState,
                            dismissed: true,
                        },
                    })
                }
                actions.clearSequence()
                if (values.currentStep < values.prompts.length) {
                    inAppPromptEventCaptureLogic.actions.reportPromptSequenceDismissed(
                        values.sequenceKey,
                        values.currentStep,
                        values.prompts.length
                    )
                }
            }
        },
        //@ts-expect-error
        [router.actions.locationChanged]: () => {
            cache.runOnClose?.()
            actions.runFirstValidSequence({})
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            posthog.onFeatureFlags(() => {
                if (featureFlagLogic.selectors.featureFlags[FEATURE_FLAGS.IN_APP_PROMPTS_EXPERIMENT] === 'test') {
                    // TODO load this from the backend
                    actions.setConfig(experimentTooltipsConfig)
                }
            })
        },
        beforeUnmount: [
            () => {
                cache.runOnClose?.()
            },
        ],
    })),
])
