import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

/** Shows why a quill control is disabled. Quill buttons stay focusable when disabled, so the tooltip still opens. */
export function QuillDisabledReasonTooltip({
    reason,
    children,
}: {
    reason: React.ReactNode
    children: React.ReactElement
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={children} />
            <TooltipContent className="max-w-80">{reason}</TooltipContent>
        </Tooltip>
    )
}
