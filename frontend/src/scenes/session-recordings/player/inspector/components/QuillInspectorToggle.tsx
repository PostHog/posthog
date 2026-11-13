import { Button, cn } from '@posthog/quill'

type QuillInspectorToggleProps = Omit<React.ComponentProps<typeof Button>, 'variant' | 'size' | 'onClick'> & {
    pressed: boolean
    onPressedChange: (pressed: boolean) => void
}

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
                'text-muted-foreground aria-pressed:bg-[color-mix(in_oklab,var(--primary)_16%,transparent)] aria-pressed:text-foreground',
                className
            )}
            {...props}
        />
    )
}
