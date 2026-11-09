import { Text, cn } from '@posthog/quill'

import type { NewsStoryApi } from 'products/today/frontend/generated/api.schemas'

import { TodayNewsCard } from './TodayNewsCard'
import { TodayNewsChart } from './TodayNewsChart'
import { TodayNewsKicker } from './TodayNewsKicker'
import type { TodayNewsRatedStory } from './todayNewsLogic'

export function TodayNewsStory({
    story,
    rated,
    wide = false,
    onDiveIn,
}: {
    story: NewsStoryApi
    rated: TodayNewsRatedStory
    wide?: boolean
    onDiveIn: () => void
}): JSX.Element {
    return (
        <li className="flex">
            <TodayNewsCard
                title={story.title}
                rated={rated}
                onDiveIn={onDiveIn}
                className={cn('grid gap-x-6 gap-y-3', wide && story.chart && '@3xl:grid-cols-2 @3xl:items-center')}
            >
                <span className="flex flex-col gap-1.5">
                    <TodayNewsKicker
                        product={story.product}
                        productLabel={story.product_label}
                        change={story.change}
                        tone={story.tone}
                    />
                    <Text size="sm" render={<span />} className="font-medium">
                        {story.title}
                    </Text>
                    <Text size="xs" variant="muted" render={<span />} className="text-pretty">
                        {story.summary}
                    </Text>
                </span>
                {story.chart ? (
                    <span className={cn('block w-full', !wide && 'max-w-sm')}>
                        <TodayNewsChart chart={story.chart} tone={story.tone} size="story" />
                    </span>
                ) : null}
            </TodayNewsCard>
        </li>
    )
}
