import { IconInfo } from '@posthog/icons'
import { Label, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillBreakdownByLabel({ info }: { info: string }): JSX.Element {
    return (
        <Label className="gap-1">
            Breakdown by
            <Tooltip>
                <TooltipTrigger render={<span className="inline-flex" tabIndex={0} aria-label="More info" />}>
                    <IconInfo className="size-4 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{info}</TooltipContent>
            </Tooltip>
        </Label>
    )
}
