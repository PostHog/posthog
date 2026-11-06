import { Text } from '@posthog/quill'

import type { NewsStoryApi } from 'products/today/frontend/generated/api.schemas'

import { TodayNewsKicker } from './TodayNewsKicker'

export function TodayNewsStoryRow({ story, onDiveIn }: { story: NewsStoryApi; onDiveIn: () => void }): JSX.Element {
    return (
        <li className="border-t py-3 first:border-t-0 first:pt-0">
            <button
                type="button"
                onClick={onDiveIn}
                aria-label={`Dive in: ${story.title}`}
                className="-mx-2 -my-1.5 flex w-[calc(100%+1rem)] cursor-pointer flex-col gap-1 rounded-md px-2 py-1.5 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                data-attr="today-news-dive-in"
            >
                <TodayNewsKicker story={story} />
                <Text size="sm" render={<span />} className="font-medium text-pretty">
                    {story.title}
                </Text>
                <Text size="xs" variant="muted" render={<span />} className="text-pretty">
                    {story.summary}
                </Text>
            </button>
        </li>
    )
}
