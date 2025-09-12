import './LemonActionableTooltip.scss'

import { Placement } from '@floating-ui/react'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'

export type LemonActionableTooltipProps = {
    title?: string
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
    title,
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
    const actionButtons = buttons?.filter((button) => button.action) ?? []
    const urlButtons = buttons?.filter((button) => button.url) ?? []
    return (
        <Popover
            visible={visible}
            referenceElement={element}
            placement={placement}
            overlay={
                <div className="LemonActionableTooltip">
                    <div className="LemonActionableTooltip__header">
                        {maxSteps === 1 && (
                            <div className="flex deprecated-space-x-4">
                                {icon && <div className="LemonActionableTooltip__icon">{icon}</div>}
                                <div className="LemonActionableTooltip__title">{title ?? ''}</div>
                            </div>
                        )}
                        <div className="LemonActionableTooltip__navigation">
                            {maxSteps > 1 && (
                                <>
                                    <LemonButton
                                        className="LemonActionableTooltip__navigation--left"
                                        onClick={previous}
                                        disabled={step === 0}
                                        size="small"
                                        type="secondary"
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
                                        type="secondary"
                                        icon={<IconChevronRight />}
                                    />
                                </>
                            )}
                        </div>
                        <div>
                            <LemonButton size="small" onClick={close}>
                                <IconX />
                            </LemonButton>
                        </div>
                    </div>
                    <div className="LemonActionableTooltip__body">
                        {maxSteps > 1 && (
                            <div className="flex deprecated-space-x-4">
                                {icon && <div className="LemonActionableTooltip__icon">{icon}</div>}
                                <div className="LemonActionableTooltip__title">{title ?? ''}</div>
                            </div>
                        )}
                        <div>{text}</div>
                    </div>
                    <div className="LemonActionableTooltip__footer">
                        {urlButtons.length > 0 && (
                            <div className="LemonActionableTooltip__url-buttons">
                                {urlButtons.map((button, index) => (
                                    <LemonButton
                                        key={index}
                                        type="secondary"
                                        icon={<IconOpenInNew />}
                                        onClick={() => window.open(button.url, '_noblank')}
                                        className="max-w-full"
                                        fullWidth
                                        center
                                    >
                                        {button.label}
                                    </LemonButton>
                                ))}
                            </div>
                        )}
                        {actionButtons.length > 0 && (
                            <div className="LemonActionableTooltip__action-buttons">
                                {actionButtons.map((button, index) => {
                                    return (
                                        <LemonButton
                                            key={index}
                                            type="primary"
                                            onClick={button.action}
                                            fullWidth
                                            center
                                        >
                                            {button.label}
                                        </LemonButton>
                                    )
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
