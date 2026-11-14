import { IconInfo } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

/** A column title with an explanation on hover. The trigger is a span, because a sortable header is already a button. */
export function GovernanceColumnHeader({ label, tooltip }: { label: string; tooltip: string }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex items-center gap-1" />}>
                {label}
                <IconInfo className="size-3 text-muted-foreground" />
            </TooltipTrigger>
            <TooltipContent>{tooltip}</TooltipContent>
        </Tooltip>
    )
}
