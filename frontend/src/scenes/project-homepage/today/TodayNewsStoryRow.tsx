import { Text } from '@posthog/quill'

import type { NewsStoryApi } from 'products/today/frontend/generated/api.schemas'

import { TodayNewsKicker } from './TodayNewsKicker'

export function TodayNewsStoryRow({ story, onDiveIn }: { story: NewsStoryApi; onDiveIn: () => void }): JSX.Element {
    return (
        <li className="flex">
            <button
                type="button"
                onClick={onDiveIn}
                aria-label={`Dive in: ${story.title}`}
                className="-m-3 flex w-full cursor-pointer flex-col gap-1.5 rounded-lg p-3 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
                data-attr="today-news-dive-in"
            >
                <TodayNewsKicker story={story} />
                <Text size="sm" render={<span />} className="font-medium">
                    {story.title}
                </Text>
                <Text size="xs" variant="muted" render={<span />} className="text-pretty">
                    {story.summary}
                </Text>
            </button>
        </li>
    )
}
