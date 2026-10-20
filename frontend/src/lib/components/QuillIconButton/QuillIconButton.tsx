import { forwardRef } from 'react'

import { Badge, Button, ButtonProps, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

export interface QuillIconButtonProps extends Omit<ButtonProps, 'children' | 'size' | 'aria-label'> {
    /** The accessible name, also shown as the tooltip. */
    label: string
    icon: React.ReactNode
    /** Shows the reason in the tooltip and disables the button. */
    disabledReason?: React.ReactNode
    /** A count shown as a badge on the button corner, hidden at zero. */
    count?: number
    size?: 'icon' | 'icon-xs' | 'icon-sm' | 'icon-lg'
}

/** An icon-only quill button with its label as the tooltip, as `design.md` requires for icon buttons. */
export const QuillIconButton = forwardRef<HTMLButtonElement, QuillIconButtonProps>(function QuillIconButton(
    { label, icon, disabledReason, count, size = 'icon', disabled, className, ...buttonProps },
    ref
): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        ref={ref}
                        size={size}
                        aria-label={count ? `${label} (${count})` : label}
                        disabled={disabled || !!disabledReason}
                        className={cn(count ? 'relative' : undefined, className)}
                        {...buttonProps}
                    />
                }
            >
                {icon}
                {count ? (
                    <Badge aria-hidden className="absolute top-0 right-0 translate-x-1/3 -translate-y-1/3">
                        {count}
                    </Badge>
                ) : null}
            </TooltipTrigger>
            <TooltipContent>{disabledReason || label}</TooltipContent>
        </Tooltip>
    )
})
