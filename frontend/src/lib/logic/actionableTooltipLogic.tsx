import React from 'react'
import ReactDOM from 'react-dom'
import { Placement } from '@floating-ui/react-dom-interactions'
import { kea, path, actions, reducers, listeners, events, selectors } from 'kea'
import type { actionableTooltipLogicType } from './actionableTooltipLogicType'
import { Popup } from 'lib/components/Popup/Popup'
import { router } from 'kea-router'
import { IconBroadcast } from 'lib/components/icons'
import { CloseOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import { LemonButton } from '@posthog/lemon-ui'
import './ActionableTooltip.scss'
import posthog from 'posthog-js'

export type Tooltip = {
    step: number
    text: string
    placement: Placement
    reference: string
}

export type TooltipRule = {
    path: string
}

export type TooltipSequence = {
    key: string
    tooltips: Tooltip[]
    rule: TooltipRule
}

export type TooltipConfig = {
    sequences: TooltipSequence[]
}

export type TooltipUserState = {
    [key: string]: {
        step: number
        completed?: boolean
        dismissed?: boolean
    }
}

type ActionableTooltipProps = {
    text: string
    placement: Placement
    reference: string
    step: number
    maxSteps: number
    visible: boolean
    close: () => void
    next?: () => void
    previous?: () => void
}

const ActionableTooltip = ({
    text,
    reference,
    placement,
    visible,
    close,
    previous,
    next,
    step,
    maxSteps,
}: ActionableTooltipProps): JSX.Element | null => {
    const element = document.querySelector(`[data-tooltip="${reference}"]`) as HTMLElement
    return element ? (
        <Popup
            visible={visible}
            referenceElement={element}
            placement={placement}
            overlay={
                <div className="ActionableTooltip">
                    <div className="ActionableTooltip__header">
                        <div className="ActionableTooltip__icon">
                            <IconBroadcast />
                        </div>
                        <LemonButton size="small" type="stealth" onClick={close}>
                            <CloseOutlined />
                        </LemonButton>
                    </div>
                    <div className="ActionableTooltip__body">{text}</div>
                    <div className="ActionableTooltip__footer">
                        <div className="ActionableTooltip__navigation">
                            <LemonButton
                                className="ActionableTooltip__navigation--left"
                                onClick={previous}
                                disabled={step === 0}
                                size="small"
                                type="stealth"
                            >
                                <LeftOutlined />
                            </LemonButton>
                            <div>
                                Tip {step + 1} of {maxSteps}
                            </div>
                            <LemonButton
                                className="ActionableTooltip__navigation--right"
                                onClick={next}
                                disabled={step === maxSteps - 1}
                                size="small"
                                type="stealth"
                            >
                                <RightOutlined />
                            </LemonButton>
                        </div>
                    </div>
                </div>
            }
            actionable
            showArrow
        />
    ) : null
}

const experimentTooltipsConfig: TooltipConfig = {
    sequences: [
        {
            key: 'experiment-tooltip',
            tooltips: [
                {
                    step: 0,
                    text: 'Hey welcome to the magical world of PostHog, where your analytics dreams come true.',
                    placement: 'bottom-end',
                    reference: 'experiment-tooltip-0',
                },
                {
                    step: 1,
                    text: 'This is a second tooltip',
                    placement: 'top-end',
                    reference: 'experiment-tooltip-1',
                },
            ],
            rule: {
                path: '/events',
            },
        },
    ],
}

export const actionableTooltipLogic = kea<actionableTooltipLogicType>([
    path(['lib', 'logic', 'tooltipLogic']),
    actions({
        tooltip: (tooltip: Tooltip) => ({
            tooltip,
        }),
        setConfig: (config: TooltipConfig) => ({ config }),
        findValidSequence: true,
        startSequence: (sequence: TooltipSequence, step?: number) => ({ sequence, step }),
        dismissSequence: true,
        clearSequence: true,
        nextTooltip: true,
        previousTooltip: true,
        updateTooltipState: true,
        setUserState: (state: TooltipUserState) => ({ state }),
    }),
    reducers(() => ({
        config: [
            null as TooltipConfig | null,
            { persist: true },
            {
                setConfig: (_, { config }) => config,
            },
        ],
        currentSequence: [
            null as TooltipSequence | null,
            {
                startSequence: (_, { sequence }) => sequence,
                clearSequence: () => null,
            },
        ],
        currentStep: [
            0,
            {
                tooltip: (_, { tooltip: { step } }) => step,
            },
        ],
        userState: [
            {} as TooltipUserState,
            { persist: true },
            {
                setUserState: (_, { state }) => state,
            },
        ],
    })),
    selectors(() => ({
        tooltips: [(s) => [s.currentSequence], (sequence: TooltipSequence) => sequence.tooltips],
        sequenceKey: [(s) => [s.currentSequence], (sequence: TooltipSequence) => sequence.key],
    })),
    listeners(({ actions, values, cache }) => ({
        setConfig: actions.findValidSequence,
        startSequence: ({ sequence, step = 0 }) => {
            setTimeout(() => actions.tooltip(sequence.tooltips[step]), 1000)
        },
        tooltip: async ({ tooltip }) => {
            cache.runOnClose?.()
            const { close, show } = cancellableTooltip(tooltip, {
                maxSteps: values.tooltips.length,
                onClose: () => {
                    actions.dismissSequence()
                },
                previous: actions.previousTooltip,
                next: actions.nextTooltip,
            })
            cache.runOnClose = close

            show.then(() => {
                actions.updateTooltipState()
            }).catch((err) => console.error(err))
        },
        updateTooltipState: () => {
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
        previousTooltip: () => {
            const step = values.currentStep - 1
            const tooltip = values.tooltips?.find((tooltip) => tooltip.step === step)
            tooltip && actions.tooltip(tooltip)
        },
        nextTooltip: () => {
            const step = values.currentStep + 1
            const tooltip = values.tooltips?.find((tooltip) => tooltip.step === step)
            tooltip && actions.tooltip(tooltip)
        },
        findValidSequence: () => {
            const pathname = router.values.currentLocation.pathname
            if (values.config) {
                for (const sequence of values.config.sequences) {
                    if (sequence.rule.path === pathname) {
                        if (values.userState[sequence.key]) {
                            const sequenceState = values.userState[sequence.key]
                            if (!sequenceState.dismissed && sequenceState.step + 1 < sequence.tooltips.length) {
                                actions.startSequence(sequence, sequenceState.step + 1)
                            }
                        } else {
                            actions.startSequence(sequence)
                        }
                        return
                    }
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
            }
        },
        //@ts-expect-error
        [router.actions.locationChanged]: () => {
            cache.runOnClose?.()
            actions.findValidSequence()
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            posthog.onFeatureFlags(() => {
                actions.setConfig(experimentTooltipsConfig)
            })
        },
        beforeUnmount: [
            () => {
                cache.runOnClose?.()
            },
        ],
    })),
])

function cancellableTooltip(
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

        function render(props: ActionableTooltipProps): void {
            ReactDOM.render(<ActionableTooltip {...props} />, div)
        }

        try {
            document.body.appendChild(div)

            const currentConfig: ActionableTooltipProps = {
                ...tooltip,
                maxSteps: config.maxSteps,
                next: config.next,
                previous: config.previous,
                close: () => {
                    destroy()
                    config.onClose()
                },
                visible: true,
            }
            trigger = destroy

            render(currentConfig)

            resolve(true)
        } catch (err) {
            reject(err)
        }
    })

    return {
        close,
        show,
    }
}
