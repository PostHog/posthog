import { IconChevronRight } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

export interface QuillRowExpandButtonProps {
    expanded: boolean
    label: string
    onToggle: () => void
    dataAttr: string
}

export function QuillRowExpandButton({ expanded, label, onToggle, dataAttr }: QuillRowExpandButtonProps): JSX.Element {
    return (
        <Button
            size="icon-sm"
            aria-label={label}
            aria-expanded={expanded}
            className="text-muted-foreground"
            onClick={onToggle}
            data-attr={dataAttr}
        >
            <IconChevronRight
                className={cn('transition-transform motion-reduce:transition-none', expanded && 'rotate-90')}
            />
        </Button>
    )
}
