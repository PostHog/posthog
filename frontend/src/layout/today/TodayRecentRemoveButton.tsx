import { IconX } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

/** The control on a Recents row that takes the record off the list. Opening the record again puts it back. */
export function TodayRecentRemoveButton({
    name,
    onRemove,
    dataAttr,
}: {
    name: string
    onRemove: () => void
    dataAttr: string
}): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon-xs"
                        aria-label={`Remove from recents: ${name}`}
                        onClick={onRemove}
                        data-attr={dataAttr}
                    />
                }
            >
                <IconX />
            </TooltipTrigger>
            <TooltipContent>Remove from recents</TooltipContent>
        </Tooltip>
    )
}
