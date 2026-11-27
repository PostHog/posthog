import { IconInfo } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

export function QuillColumnHeaderTooltip({
    title,
    tooltip,
    iconClassName,
}: {
    title: React.ReactNode
    tooltip: React.ReactNode
    iconClassName?: string
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex items-center gap-1" />}>
                {title}
                <IconInfo className={cn('size-3 shrink-0', iconClassName)} />
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
        </Tooltip>
    )
}
