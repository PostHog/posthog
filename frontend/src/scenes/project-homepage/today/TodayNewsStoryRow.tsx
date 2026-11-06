import { IconArrowRight } from '@posthog/icons'
import { Button, IconStack, IconStackItem, Text } from '@posthog/quill'

import { TodayChange } from './TodayChange'
import type { TodayNewsStory } from './todayNewsEdition'
import { productIcon } from './todayRowIcons'

export function TodayNewsStoryRow({ story, onDiveIn }: { story: TodayNewsStory; onDiveIn: () => void }): JSX.Element {
    const icon = productIcon(story.product)

    return (
        <article className="flex flex-col gap-1 border-t py-4 first:border-t-0 first:pt-0">
            <span className="flex items-center gap-2">
                <IconStack className="TodayRow__icons">
                    <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
                </IconStack>
                <Text size="sm" variant="muted">
                    {story.productLabel}
                </Text>
                <TodayChange change={story.change} tone={story.tone} />
            </span>
            <Text render={<h4 />} className="m-0 text-base font-medium">
                {story.title}
            </Text>
            <Text size="sm" variant="muted" render={<p />} className="m-0">
                {story.summary}
            </Text>
            <div className="-ml-2">
                <Button onClick={onDiveIn} data-attr="today-news-dive-in">
                    Dive in
                    <IconArrowRight />
                </Button>
            </div>
        </article>
    )
}
