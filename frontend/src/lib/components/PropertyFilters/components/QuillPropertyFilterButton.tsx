import React from 'react'

import { IconX } from '@posthog/icons'
import { Button, ButtonGroup, Chip, ChipClose, cn } from '@posthog/quill'

export type PropertyFilterTriggerProps = React.HTMLAttributes<HTMLButtonElement> & {
    ref?: React.Ref<HTMLButtonElement>
}

export interface QuillPropertyFilterButtonProps {
    icon: React.ReactNode
    displayLabel: string
    wraps: boolean
    tooltip?: React.ReactNode
    onClick?: () => void
    onClose?: () => void
    disabledReason?: string
    triggerProps?: PropertyFilterTriggerProps
}

export const QuillPropertyFilterButton = React.forwardRef<HTMLElement, QuillPropertyFilterButtonProps>(
    function QuillPropertyFilterButton(
        { icon, displayLabel, wraps, tooltip, onClick, onClose, disabledReason, triggerProps },
        ref
    ): JSX.Element {
        const content = (
            <>
                {icon}
                <span className={cn('min-w-0', wraps ? 'text-left' : 'truncate')}>{displayLabel}</span>
            </>
        )
        const removable = onClose !== undefined && !disabledReason

        if (onClick === undefined && triggerProps === undefined) {
            return (
                <Chip
                    ref={ref as React.Ref<HTMLDivElement>}
                    className={cn('ph-no-capture min-w-0', wraps && 'h-auto py-1 whitespace-normal')}
                    tooltip={tooltip}
                    disabledReason={disabledReason}
                >
                    {content}
                    {removable && <ChipClose aria-label="Remove filter" tooltip="Remove filter" onClick={onClose} />}
                </Chip>
            )
        }

        const button = (
            <Button
                ref={ref as React.Ref<HTMLButtonElement>}
                variant="outline"
                left
                className={cn('ph-no-capture min-w-0', wraps && 'h-auto py-1 whitespace-normal')}
                tooltip={tooltip}
                disabledReason={disabledReason}
                onClick={onClick}
                {...triggerProps}
            >
                {content}
            </Button>
        )

        if (!removable) {
            return button
        }

        return (
            <ButtonGroup className="min-w-0 max-w-full">
                {button}
                <Button
                    variant="outline"
                    size="icon"
                    aria-label="Remove filter"
                    tooltip="Remove filter"
                    onClick={onClose}
                >
                    <IconX />
                </Button>
            </ButtonGroup>
        )
    }
)
