import { forwardRef } from 'react'

import { IconX } from '@posthog/icons'
import { Button, ButtonGroup, SelectTriggerIcon, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

export interface QuillTaxonomicTriggerProps extends Omit<
    React.ButtonHTMLAttributes<HTMLButtonElement>,
    'children' | 'onClick' | 'disabled' | 'className'
> {
    children: React.ReactNode
    icon?: React.ReactNode
    /** `null` hides the chevron; `undefined` keeps the default. */
    sideIcon?: React.ReactNode
    fullWidth?: boolean
    disabled?: boolean
    disabledReason?: React.ReactNode
    tooltip?: React.ReactNode
    open?: boolean
    className?: string
    onClick?: React.MouseEventHandler<HTMLElement>
    /** Adds a clear button beside the trigger. */
    onClear?: () => void
    'data-attr'?: string
}

/** The quill trigger for taxonomic pickers, the counterpart of their `LemonButton` trigger. */
export const QuillTaxonomicTrigger = forwardRef<HTMLElement, QuillTaxonomicTriggerProps>(function QuillTaxonomicTrigger(
    {
        children,
        icon,
        sideIcon,
        fullWidth,
        disabled,
        disabledReason,
        tooltip,
        open,
        className,
        onClick,
        onClear,
        'data-attr': dataAttr,
        ...buttonProps
    },
    ref
): JSX.Element {
    const trigger = (
        <Button
            {...buttonProps}
            ref={onClear ? undefined : (ref as React.Ref<HTMLButtonElement>)}
            variant="outline"
            left
            disabled={disabled || !!disabledReason}
            aria-expanded={open}
            onClick={onClick}
            data-attr={dataAttr}
            className={cn('min-w-0 max-w-full', fullWidth && !onClear && 'w-full', onClear && 'flex-1', className)}
        >
            {icon}
            <span className="min-w-0 flex-1 truncate text-start">{children}</span>
            {sideIcon === undefined ? <SelectTriggerIcon /> : sideIcon}
        </Button>
    )
    const tooltipContent = disabledReason || (!open ? tooltip : null)
    const triggerWithTooltip = tooltipContent ? (
        <Tooltip>
            <TooltipTrigger render={trigger} />
            <TooltipContent>{tooltipContent}</TooltipContent>
        </Tooltip>
    ) : (
        trigger
    )
    if (!onClear) {
        return triggerWithTooltip
    }
    return (
        <ButtonGroup ref={ref as React.Ref<HTMLDivElement>} className={cn(fullWidth && 'w-full')}>
            {triggerWithTooltip}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={<Button variant="outline" size="icon" aria-label="Clear selection" onClick={onClear} />}
                >
                    <IconX />
                </TooltipTrigger>
                <TooltipContent>Clear selection</TooltipContent>
            </Tooltip>
        </ButtonGroup>
    )
})
