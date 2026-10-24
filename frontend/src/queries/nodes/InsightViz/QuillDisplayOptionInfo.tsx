import { IconInfo } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillDisplayOptionInfo({ info }: { info: string }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="inline-flex text-muted-foreground" />}>
                <IconInfo />
            </TooltipTrigger>
            <TooltipContent className="max-w-64">{info}</TooltipContent>
        </Tooltip>
    )
}
