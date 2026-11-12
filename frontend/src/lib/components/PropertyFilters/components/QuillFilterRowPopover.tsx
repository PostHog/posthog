import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

export interface QuillFilterRowPopoverProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    trigger: React.ComponentProps<typeof PopoverTrigger>['render']
    children: React.ReactNode
}

// The Lemon editor inside opens its own Lemon popovers in a separate portal, which this popover would treat as outside.
function isInLemonPopover(event: Event | undefined): boolean {
    const target = event instanceof FocusEvent ? event.relatedTarget : event?.target
    return target instanceof Element && target.closest('.Popover') !== null
}

export function QuillFilterRowPopover({
    open,
    onOpenChange,
    trigger,
    children,
}: QuillFilterRowPopoverProps): JSX.Element {
    return (
        <Popover
            open={open}
            onOpenChange={(nextOpen, details) => {
                if (
                    !nextOpen &&
                    (details.reason === 'outside-press' || details.reason === 'focus-out') &&
                    isInLemonPopover(details.event)
                ) {
                    return
                }
                onOpenChange(nextOpen)
            }}
        >
            <PopoverTrigger render={trigger} />
            <PopoverContent side="bottom" align="start" className="w-auto gap-0 p-2">
                <div data-not-quill>{children}</div>
            </PopoverContent>
        </Popover>
    )
}
