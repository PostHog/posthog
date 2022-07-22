import React from 'react'
import { Placement } from '@floating-ui/react-dom-interactions'
import { Popup } from 'lib/components/Popup/Popup'
import { IconBroadcast } from 'lib/components/icons'
import { CloseOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
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
}: LemonActionableTooltipProps): JSX.Element | null => {
    return (
        <Popup
            visible={visible}
            referenceElement={element}
            placement={placement}
            overlay={
                <div className="LemonActionableTooltip">
                    <div className="LemonActionableTooltip__header">
                        <div className="LemonActionableTooltip__icon">
                            <IconBroadcast />
                        </div>
                        <LemonButton size="small" type="stealth" onClick={close}>
                            <CloseOutlined />
                        </LemonButton>
                    </div>
                    <div className="LemonActionableTooltip__body">{text}</div>
                    <div className="LemonActionableTooltip__footer">
                        {maxSteps > 1 && (
                            <div className="LemonActionableTooltip__navigation">
                                <LemonButton
                                    className="LemonActionableTooltip__navigation--left"
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
                                    className="LemonActionableTooltip__navigation--right"
                                    onClick={next}
                                    disabled={step === maxSteps - 1}
                                    size="small"
                                    type="stealth"
                                >
                                    <RightOutlined />
                                </LemonButton>
                            </div>
                        )}
                        {/* <div>
                            <LemonButton>Hello</LemonButton>
                        </div> */}
                    </div>
                </div>
            }
            actionable
            showArrow
        />
    )
}
