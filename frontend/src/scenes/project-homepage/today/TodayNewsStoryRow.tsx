import { IconArrowRight } from '@posthog/icons'
import { Card, IconStack, IconStackItem, Text } from '@posthog/quill'

import { TodayChange } from './TodayChange'
import type { TodayNewsStory } from './todayNewsEdition'
import { productIcon } from './todayRowIcons'

export function TodayNewsStoryRow({ story, onDiveIn }: { story: TodayNewsStory; onDiveIn: () => void }): JSX.Element {
    const icon = productIcon(story.product)

    return (
        <Card size="sm" className="flex-1 p-0">
            <button
                type="button"
                onClick={onDiveIn}
                aria-label={`Dive in: ${story.title}`}
                className="group/story flex h-full w-full min-w-0 cursor-pointer items-center gap-3 px-4 py-3.5 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
                data-attr="today-news-dive-in"
            >
                <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="flex items-center gap-2">
                        <IconStack className="TodayRow__icons">
                            <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
                        </IconStack>
                        <Text size="xs" variant="muted" render={<span />}>
                            {story.productLabel}
                        </Text>
                        <TodayChange change={story.change} tone={story.tone} />
                    </span>
                    <Text size="sm" render={<span />} className="font-medium">
                        {story.title}
                    </Text>
                    <Text size="xs" variant="muted" render={<span />}>
                        {story.summary}
                    </Text>
                </span>
                <IconArrowRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/story:opacity-100 group-focus-visible/story:opacity-100 motion-reduce:transition-none" />
            </button>
        </Card>
    )
}
