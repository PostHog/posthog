import { Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

export function QuillListDisplay({ list }: { list: string[] }): JSX.Element {
    if (list.length === 0) {
        return (
            <Text size="xs" variant="muted" render={<span />}>
                -
            </Text>
        )
    }

    const joinedList = list.join(', ')

    return (
        <Tooltip>
            <TooltipTrigger render={<span tabIndex={0} className="line-clamp-2 break-words" />}>
                <Text size="xs" variant="muted" render={<span />}>
                    {joinedList}
                </Text>
            </TooltipTrigger>
            <TooltipContent className="max-w-80">{joinedList}</TooltipContent>
        </Tooltip>
    )
}
