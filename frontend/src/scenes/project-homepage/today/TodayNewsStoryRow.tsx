import { IconArrowRight } from '@posthog/icons'
import { Text } from '@posthog/quill'

import { TodayChange } from './TodayChange'
import type { TodayNewsStory } from './todayNewsEdition'
import { productIcon } from './todayRowIcons'

export function TodayNewsStoryRow({ story, onDiveIn }: { story: TodayNewsStory; onDiveIn: () => void }): JSX.Element {
    return (
        <li className="border-t">
            <button
                type="button"
                onClick={onDiveIn}
                aria-label={`Dive in: ${story.title}`}
                className="group/story -mx-2 flex w-[calc(100%+1rem)] cursor-pointer items-start gap-3 rounded-md px-2 py-3 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
                data-attr="today-news-dive-in"
            >
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="flex items-center gap-2">
                        <span className="flex items-center gap-1.5 text-muted-foreground [&_svg]:size-3.5">
                            {productIcon(story.product).glyph}
                            <Text size="xs" variant="muted" render={<span />}>
                                {story.productLabel}
                            </Text>
                        </span>
                        <TodayChange change={story.change} tone={story.tone} />
                    </span>
                    <Text size="sm" render={<span />} className="font-medium">
                        {story.title}
                    </Text>
                    <Text size="sm" variant="muted" render={<span />}>
                        {story.summary}
                    </Text>
                </span>
                <IconArrowRight className="mt-5 size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/story:opacity-100 group-focus-visible/story:opacity-100 motion-reduce:transition-none" />
            </button>
        </li>
    )
}
