import { Button, Popover, PopoverContent, Text } from '@posthog/quill'

/** A card the design demo shows beside what its cursor points at, with one button to move on. */
export function TodayDemoHint({
    anchor,
    side,
    align,
    title,
    description,
    actionLabel,
    onAction,
    onDismiss,
}: {
    anchor: Element | { getBoundingClientRect: () => DOMRect }
    side: 'top' | 'right' | 'bottom' | 'left'
    align: 'start' | 'center' | 'end'
    title: string
    description: string
    actionLabel: string
    onAction: () => void
    /** An outside click or Esc. */
    onDismiss: () => void
}): JSX.Element {
    return (
        <Popover open onOpenChange={(open) => !open && onDismiss()}>
            <PopoverContent anchor={anchor} side={side} align={align} arrow className="max-w-64">
                <div className="flex flex-col gap-1">
                    <Text size="sm" weight="semibold" render={<h3 />} className="m-0">
                        {title}
                    </Text>
                    <Text size="xs" variant="muted" className="m-0">
                        {description}
                    </Text>
                </div>
                <Button variant="outline" size="sm" className="self-end" onClick={onAction}>
                    {actionLabel}
                </Button>
            </PopoverContent>
        </Popover>
    )
}
