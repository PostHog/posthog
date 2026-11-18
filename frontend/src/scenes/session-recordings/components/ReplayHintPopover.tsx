import { IconX } from '@posthog/icons'
import { Button, cn, Popover, PopoverContent } from '@posthog/quill'

interface ReplayHintPopoverProps {
    anchor: HTMLElement | null
    onDismiss: () => void
    children: React.ReactNode
    action?: { label: string; onClick: () => void; dataAttr: string }
    side?: React.ComponentProps<typeof PopoverContent>['side']
    align?: React.ComponentProps<typeof PopoverContent>['align']
    container?: HTMLElement | null
    /** A smaller hint that informs without drawing the eye. */
    compact?: boolean
    dataAttr: string
}

/** A one-time pointer at a control. It stays until dismissed, so a click elsewhere does not close it. */
export function ReplayHintPopover({
    anchor,
    onDismiss,
    children,
    action,
    side = 'bottom',
    align = 'end',
    container,
    compact = false,
    dataAttr,
}: ReplayHintPopoverProps): JSX.Element | null {
    if (!anchor) {
        return null
    }
    return (
        <Popover
            open
            onOpenChange={(open, details) => {
                if (!open && details.reason === 'escape-key') {
                    onDismiss()
                }
            }}
        >
            <PopoverContent
                anchor={anchor}
                arrow
                side={side}
                align={align}
                container={container ?? undefined}
                initialFocus={false}
                finalFocus={false}
                // Base UI flags the positioner when the anchor is scrolled out of view.
                className={cn(
                    '[[data-anchor-hidden]_&]:invisible',
                    compact ? 'w-56 flex-row items-start gap-1 p-2 text-xs' : 'w-72 gap-2 text-sm'
                )}
                data-attr={dataAttr}
            >
                <div className="flex-1">{children}</div>
                {compact ? (
                    <Button
                        size="icon-xs"
                        onClick={onDismiss}
                        aria-label="Dismiss"
                        className="shrink-0 text-muted-foreground"
                        data-attr={`${dataAttr}-dismiss`}
                    >
                        <IconX />
                    </Button>
                ) : (
                    <div className="flex justify-end gap-1">
                        {action && (
                            <Button variant="primary" size="sm" onClick={action.onClick} data-attr={action.dataAttr}>
                                {action.label}
                            </Button>
                        )}
                        <Button variant="outline" size="sm" onClick={onDismiss} data-attr={`${dataAttr}-dismiss`}>
                            Dismiss
                        </Button>
                    </div>
                )}
            </PopoverContent>
        </Popover>
    )
}
