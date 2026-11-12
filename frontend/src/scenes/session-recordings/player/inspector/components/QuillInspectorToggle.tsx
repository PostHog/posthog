import { Button, cn } from '@posthog/quill'

type QuillInspectorToggleProps = Omit<React.ComponentProps<typeof Button>, 'variant' | 'size' | 'onClick'> & {
    pressed: boolean
    onPressedChange: (pressed: boolean) => void
}

/**
 * A borderless toggle for the inspector's filter and settings rows: muted text when off, a filled block when on.
 * It is a quill Button and not a quill Toggle because the rows need `tooltip`, `disabledReason` and `loading`.
 */
export function QuillInspectorToggle({
    pressed,
    onPressedChange,
    className,
    ...props
}: QuillInspectorToggleProps): JSX.Element {
    return (
        <Button
            variant="default"
            size="sm"
            aria-pressed={pressed}
            onClick={() => onPressedChange(!pressed)}
            className={cn(
                'text-muted-foreground aria-pressed:bg-fill-selected aria-pressed:text-foreground',
                className
            )}
            {...props}
        />
    )
}
