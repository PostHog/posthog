import { ReactNode } from 'react'

import { Badge, Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

const VISIBLE_TAGS = 4

export function QuillTagList({
    tags,
    onMoreClick,
    tooltip,
}: {
    tags: string[]
    onMoreClick?: () => void
    /** Content of the "+N more" tooltip. Defaults to the hidden tags, comma separated. */
    tooltip?: ReactNode
}): JSX.Element {
    const hiddenCount = tags.length - VISIBLE_TAGS
    const moreTooltip = tooltip ?? tags.slice(VISIBLE_TAGS).join(', ')

    return (
        <span className="flex flex-wrap items-center gap-1">
            {tags.slice(0, VISIBLE_TAGS).map((tag) => (
                <Badge key={tag}>{tag}</Badge>
            ))}
            {hiddenCount > 0 &&
                (onMoreClick ? (
                    <Button size="xs" variant="outline" tooltip={moreTooltip} onClick={onMoreClick}>
                        {`+${hiddenCount} more`}
                    </Button>
                ) : (
                    <Tooltip>
                        <TooltipTrigger render={<Badge tabIndex={0} />}>{`+${hiddenCount} more`}</TooltipTrigger>
                        <TooltipContent>{moreTooltip}</TooltipContent>
                    </Tooltip>
                ))}
        </span>
    )
}
