import { IconPlayFilled } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export function TodayFeedReplay({
    page,
    caption,
    to,
    onOpen,
}: {
    page: string | null
    caption: string
    to: string
    onOpen: () => void
}): JSX.Element {
    return (
        <LinkPrimitive
            to={to}
            onClick={onOpen}
            className="group relative flex aspect-video flex-col justify-between overflow-hidden rounded-lg border border-border bg-muted p-3"
            data-attr="today-feed-replay"
        >
            <Text size="xs" variant="muted" className="truncate" translate="no">
                {page ?? 'Recording'}
            </Text>
            <span className="absolute inset-0 flex items-center justify-center" aria-hidden>
                <span className="flex size-14 items-center justify-center rounded-full bg-foreground text-background transition-transform group-hover:scale-105 motion-reduce:transition-none [&_svg]:size-6">
                    <IconPlayFilled />
                </span>
            </span>
            <span className="relative flex items-center justify-between gap-2">
                <Text size="xs" weight="medium" className="truncate">
                    {caption}
                </Text>
                <Text size="xs" variant="muted" className="shrink-0">
                    Watch recording
                </Text>
            </span>
        </LinkPrimitive>
    )
}
