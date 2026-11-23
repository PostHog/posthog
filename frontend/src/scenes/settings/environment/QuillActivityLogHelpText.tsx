import { IconInfo } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillActivityLogHelpText({ text, help }: { text: string; help: string }): JSX.Element {
    return (
        <Text size="xs" render={<p className="m-0 flex items-center gap-1" />}>
            {text}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={<Button size="icon-xs" aria-label="More information" className="text-muted-foreground" />}
                >
                    <IconInfo />
                </TooltipTrigger>
                <TooltipContent className="max-w-80">{help}</TooltipContent>
            </Tooltip>
        </Text>
    )
}
