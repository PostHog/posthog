import { Badge, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillEventHealthWarning({
    label,
    explanation,
}: {
    label: string
    explanation: JSX.Element
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<Badge variant="warning" data-attr="action-event-health-warning" />}>
                {label}
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{explanation}</TooltipContent>
        </Tooltip>
    )
}
