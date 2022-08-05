import React from 'react'
import { Placement } from '@floating-ui/react-dom-interactions'
import { Popup } from 'lib/components/Popup/Popup'
import { IconOpenInNew } from 'lib/components/icons'
import { IconClose, IconChevronLeft, IconChevronRight } from 'lib/components/icons'
import { LemonButton } from '@posthog/lemon-ui'
import './LemonActionableTooltip.scss'

export type LemonActionableTooltipProps = {
    text: string
    placement: Placement
    step: number
    maxSteps: number
    visible: boolean
    close: () => void
    element?: HTMLElement
    next?: () => void
    previous?: () => void
    buttons?: { label: string; url?: string; action?: () => void }[]
    icon?: JSX.Element
}

export const LemonActionableTooltip = ({
    text,
    element,
    placement,
    visible,
    close,
    previous,
    next,
    step,
    maxSteps,
    buttons,
    icon,
}: LemonActionableTooltipProps): JSX.Element | null => {
    return (
        <Popup
            visible={visible}
            referenceElement={element}
            placement={placement}
            overlay={
                <div className="LemonActionableTooltip">
                    <div className="LemonActionableTooltip__header">
                        {icon && <div className="LemonActionableTooltip__icon">{icon}</div>}
                        <LemonButton size="small" type="stealth" onClick={close}>
                            <IconClose />
                        </LemonButton>
                    </div>
                    <div className="LemonActionableTooltip__body">{text}</div>
                    <div className="LemonActionableTooltip__footer">
                        <div className="LemonActionableTooltip__navigation">
                            {maxSteps > 1 && (
                                <>
                                    <LemonButton
                                        className="LemonActionableTooltip__navigation--left"
                                        onClick={previous}
                                        disabled={step === 0}
                                        size="small"
                                        type="stealth"
                                        icon={<IconChevronLeft />}
                                    />
                                    <div>
                                        Tip {step + 1} of {maxSteps}
                                    </div>
                                    <LemonButton
                                        className="LemonActionableTooltip__navigation--right"
                                        onClick={next}
                                        disabled={step === maxSteps - 1}
                                        size="small"
                                        type="stealth"
                                        icon={<IconChevronRight />}
                                    />
                                </>
                            )}
                        </div>
                        {buttons && (
                            <div className="LemonActionableTooltip__buttons">
                                {buttons.map((button, index) => {
                                    if (button.url) {
                                        return (
                                            <LemonButton
                                                key={index}
                                                type="secondary"
                                                icon={<IconOpenInNew />}
                                                onClick={() => window.open(button.url, '_noblank')}
                                            >
                                                {button.label}
                                            </LemonButton>
                                        )
                                    }
                                    if (button.action) {
                                        return (
                                            <LemonButton key={index} type="secondary" onClick={button.action}>
                                                {button.label}
                                            </LemonButton>
                                        )
                                    }
                                })}
                            </div>
                        )}
                    </div>
                </div>
            }
            actionable
            showArrow
        />
    )
}
