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
import { FEATURE_FLAGS } from 'lib/constants'
import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { now } from 'lib/dayjs'
import wcmatch from 'wildcard-match'
import { IconBarChart, IconGauge, IconLive } from 'lib/components/icons'

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
    reference: string
    buttons: PromptButton[]
    icon?: string
}

export type Tooltip = Prompt & { type: 'tooltip' }

export type PromptRule = {
    path: string
}

export type PromptSequence = {
    key: string
    prompts: Prompt[]
    rule: PromptRule
    type: string
}

export type PromptConfig = {
    sequences: PromptSequence[]
}

export type PromptState = {
    key: string
    last_updated_at: string
    step: number
    completed?: boolean
    dismissed?: boolean
}

export type ValidSequenceWithState = {
    sequence: PromptSequence
    state: { step: number; completed?: boolean; dismissed?: boolean }
}

export type PromptUserState = {
    [key: string]: PromptState
}

// we show a new sequence with 1 second delay, because users immediately dismiss prompts that are invasive
const NEW_SEQUENCE_DELAY = 1000

const iconMap = {
    'live-events': <IconLive />,
    dashboard: <IconGauge />,
    insight: <IconBarChart />,
}

function cancellableTooltipWithRetries(
    tooltip: Tooltip,
    onAction: (action: string) => void,
    options: { maxSteps: number; onClose: () => void; next: () => void; previous: () => void }
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
                let props: LemonActionableTooltipProps = {
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
                        ? (document.querySelector(`[data-tooltip="${tooltip.reference}"]`) as HTMLElement)
                        : null
                    if (!element) {
                        throw 'Prompt reference element not found'
                    }
                    props = { ...props, element }
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

export const inAppPromptLogic = kea<inAppPromptLogicType>([
    path(['lib', 'logic', 'inAppPrompt']),
    connect([inAppPromptEventCaptureLogic]),
    actions({
        tooltip: (tooltip: Tooltip) => ({ tooltip }),
        findValidSequences: true,
        setValidSequences: (validSequences: ValidSequenceWithState[]) => ({ validSequences }),
        runFirstValidSequence: (options: { runDismissedOrCompleted?: boolean; restart?: boolean }) => ({ options }),
        runSequence: (sequence: PromptSequence, step: number) => ({ sequence, step }),
        runPrompt: (prompt: Prompt) => ({ prompt }),
        closePrompts: true,
        dismissSequence: true,
        clearSequence: true,
        nextPrompt: true,
        previousPrompt: true,
        updatePromptState: (update: Partial<PromptState>) => ({ update }),
        setUserState: (state: PromptUserState) => ({ state }),
        syncState: (options: { forceRun?: boolean }) => ({ options }),
        setSequences: (sequences: PromptSequence[]) => ({ sequences }),
        promptAction: (action: string) => ({ action }),
        skipTutorial: true,
    }),
    reducers(() => ({
        sequences: [
            [] as PromptSequence[],
            { persist: true },
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
            { persist: true },
            {
                setUserState: (_, { state }) => state,
            },
        ],
        hasSkippedTutorial: [
            false,
            { persist: true },
            {
                skipTutorial: () => true,
            },
        ],
        validSequences: [
            [] as { sequence: PromptSequence; state: { step: number; completed?: boolean; dismissed?: boolean } }[],
            {
                setValidSequences: (_, { validSequences }) => validSequences,
            },
        ],
        isPromptVisible: [
            false,
            {
                runPrompt: () => true,
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
        syncState: async ({ options }) => {
            try {
                const updatedState = await api.update(
                    `api/projects/${teamLogic.values.currentTeamId}/prompts/my_prompts`,
                    values.userState
                )
                if (updatedState) {
                    if (JSON.stringify(values.userState) !== JSON.stringify(updatedState['state'])) {
                        actions.setUserState(updatedState['state'])
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
        runSequence: ({ sequence, step = 0 }) => {
            const prompt = sequence.prompts.find((prompt) => prompt.step === step)
            if (prompt) {
                actions.runPrompt(prompt)
                if (step === sequence.prompts.length - 1) {
                    actions.updatePromptState({
                        completed: true,
                    })
                    inAppPromptEventCaptureLogic.actions.reportPromptSequenceCompleted(
                        sequence.key,
                        step,
                        values.prompts.length
                    )
                }
            }
        },
        runPrompt: ({ prompt }) => {
            switch (prompt.type) {
                case 'tooltip':
                    actions.tooltip(prompt)
                    break
                default:
                    break
            }
        },
        tooltip: async ({ tooltip }) => {
            const { close, show } = cancellableTooltipWithRetries(tooltip, actions.promptAction, {
                maxSteps: values.prompts.length,
                onClose: () => {
                    actions.dismissSequence()
                },
                previous: actions.previousPrompt,
                next: actions.nextPrompt,
            })
            cache.runOnClose = close

            show.then(() => {
                actions.updatePromptState({ step: values.currentStep })
            }).catch((err) => console.error(err))
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
                const isWildcardMatch = wcmatch(sequence.rule.path)
                if (isWildcardMatch(pathname)) {
                    if (sequence.type === 'product-tour' && values.hasSkippedTutorial) {
                        continue
                    }
                    if (values.userState[sequence.key]) {
                        const sequenceState = values.userState[sequence.key]
                        const completed = !!sequenceState.completed || sequenceState.step === sequence.prompts.length
                        const dismissed = !!sequenceState.dismissed
                        if (
                            sequence.type !== 'product-tour' &&
                            (completed || dismissed || sequenceState.step === sequence.prompts.length)
                        ) {
                            continue
                        }
                        valid.push({
                            sequence,
                            state: {
                                step: sequenceState.step + 1,
                                completed,
                                dismissed,
                            },
                        })
                    } else {
                        valid.push({ sequence, state: { step: 0 } })
                    }
                }
            }
            actions.setValidSequences(valid)
        },
        setValidSequences: () => actions.runFirstValidSequence({}),
        runFirstValidSequence: ({ options }) => {
            if (values.validSequences) {
                actions.closePrompts()
                let firstValid = null
                if (options.runDismissedOrCompleted) {
                    firstValid = values.validSequences[0]
                } else {
                    firstValid = values.validSequences.filter(
                        (sequence) => !sequence.state.completed && !sequence.state.dismissed
                    )?.[0]
                }
                if (firstValid) {
                    const { sequence, state } = firstValid
                    setTimeout(
                        () => actions.runSequence(sequence, options.restart ? 0 : state.step),
                        NEW_SEQUENCE_DELAY
                    )
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
        setUserState: () => actions.syncState({}),
        promptAction: ({ action }) => {
            switch (action) {
                case 'skip':
                    actions.closePrompts()
                    actions.skipTutorial()
                    inAppPromptEventCaptureLogic.actions.reportTutorialSkipped()
                    break
                default:
                    break
            }
        },
        //@ts-expect-error
        [router.actions.locationChanged]: () => {
            actions.closePrompts()
            actions.findValidSequences()
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            posthog.onFeatureFlags(async (_, variants) => {
                if (variants[FEATURE_FLAGS.IN_APP_PROMPTS_EXPERIMENT] === 'test') {
                    actions.syncState({ forceRun: true })
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
