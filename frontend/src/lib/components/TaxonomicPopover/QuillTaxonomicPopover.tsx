import type { Placement } from '@floating-ui/react'
import { forwardRef } from 'react'

import { IconX } from '@posthog/icons'
import { Button, ButtonGroup, Popover, PopoverContent, PopoverTrigger, SelectTriggerIcon, cn } from '@posthog/quill'

import type { LemonButtonProps } from 'lib/lemon-ui/LemonButton'
import { quillButtonVariant } from 'lib/lemon-ui/LemonButton/quillButtonVariant'
import { isInsideOpenPopover } from 'lib/lemon-ui/Popover/Popover'
import { resolveTooltipTitle } from 'lib/lemon-ui/Tooltip/resolveTooltipTitle'
import type { TooltipTitle } from 'lib/lemon-ui/Tooltip/Tooltip'

export interface QuillTaxonomicPopoverProps {
    buttonProps: Omit<LemonButtonProps, 'sideAction'>
    open: boolean
    onOpenChange: (open: boolean) => void
    label: React.ReactNode
    tooltip?: TooltipTitle
    onClear?: () => void
    showChevron: boolean
    placement?: Placement
    children: React.ReactNode
}

export const QuillTaxonomicPopover = forwardRef<HTMLButtonElement, QuillTaxonomicPopoverProps>(
    function QuillTaxonomicPopover(
        { buttonProps, open, onOpenChange, label, tooltip, onClear, showChevron, placement, children },
        ref
    ): JSX.Element {
        const [side, align] = (placement ?? 'bottom-start').split('-') as [
            'top' | 'bottom' | 'left' | 'right',
            'start' | 'end' | undefined,
        ]

        const trigger = (
            <PopoverTrigger
                render={
                    <Button
                        ref={ref}
                        id={buttonProps.id}
                        variant={quillButtonVariant(buttonProps.type ?? 'secondary')}
                        disabled={buttonProps.disabled}
                        disabledReason={buttonProps.disabledReason || undefined}
                        tooltip={tooltip === undefined ? undefined : resolveTooltipTitle(tooltip)}
                        data-attr={buttonProps['data-attr']}
                        data-attr-id={buttonProps['data-attr-id'] ?? buttonProps['data-attr']}
                        left={buttonProps.fullWidth}
                        className={cn('min-w-0', buttonProps.fullWidth && 'w-full', buttonProps.className)}
                    >
                        {buttonProps.icon}
                        <span className={cn('min-w-0', buttonProps.fullWidth && 'flex-1 text-left', 'truncate')}>
                            {label}
                        </span>
                        {showChevron && <SelectTriggerIcon />}
                    </Button>
                }
            />
        )

        return (
            <Popover
                open={open}
                onOpenChange={(next, details) => {
                    // The filter's Lemon popovers (event definitions, the category menu) portal outside this one.
                    const landedOn =
                        details.reason === 'focus-out'
                            ? (details.event as FocusEvent).relatedTarget
                            : details.reason === 'outside-press'
                              ? details.event.target
                              : null
                    if (!next && isInsideOpenPopover(landedOn)) {
                        details.cancel()
                        return
                    }
                    onOpenChange(next)
                }}
            >
                {onClear ? (
                    <ButtonGroup className={cn('min-w-0', buttonProps.fullWidth && 'w-full')}>
                        {trigger}
                        <Button
                            variant={quillButtonVariant(buttonProps.type ?? 'secondary')}
                            size="icon"
                            aria-label="Clear selection"
                            tooltip="Clear selection"
                            onClick={onClear}
                        >
                            <IconX />
                        </Button>
                    </ButtonGroup>
                ) : (
                    trigger
                )}
                <PopoverContent side={side} align={align ?? 'center'} className="w-auto p-0">
                    {/* The filter is Lemon, so it keeps Lemon's colors inside the quill popover. */}
                    <div data-not-quill>{children}</div>
                </PopoverContent>
            </Popover>
        )
    }
)
