import { IconPlus } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export interface QuillAddFilterGroupButtonProps {
    onClick: () => void
    disabledReason?: string
    className?: string
    'data-attr'?: string
}

export function QuillAddFilterGroupButton({
    onClick,
    disabledReason,
    className,
    'data-attr': dataAttr,
}: QuillAddFilterGroupButtonProps): JSX.Element {
    const button = (
        <Button
            variant="outline"
            onClick={onClick}
            disabled={!!disabledReason}
            className={className}
            data-attr={dataAttr}
        >
            <IconPlus />
            Add filter group
        </Button>
    )
    if (!disabledReason) {
        return button
    }
    return (
        <Tooltip>
            <TooltipTrigger render={button} />
            <TooltipContent className="max-w-80">{disabledReason}</TooltipContent>
        </Tooltip>
    )
}
