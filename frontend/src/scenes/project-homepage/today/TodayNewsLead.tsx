import { Suspense, lazy } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Skeleton, Text } from '@posthog/quill'

import { retryImport } from 'lib/utils/retryImport'

import { TodayChange } from './TodayChange'
import type { TodayNewsLeadStory } from './todayNewsEdition'
import { productIcon } from './todayRowIcons'

const TodaySparkline = lazy(() =>
    retryImport(() => import('./TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

export function TodayNewsLead({ story, onDiveIn }: { story: TodayNewsLeadStory; onDiveIn: () => void }): JSX.Element {
    return (
        <button
            type="button"
            onClick={onDiveIn}
            aria-label={`Dive in: ${story.title}`}
            className="group/story -mx-2 flex w-[calc(100%+1rem)] cursor-pointer flex-col gap-1 rounded-md px-2 pt-1 pb-3 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
            data-attr="today-news-dive-in"
        >
            <span className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-muted-foreground [&_svg]:size-3.5">
                    {productIcon(story.product).glyph}
                    <Text size="xs" variant="muted" render={<span />}>
                        {story.productLabel}
                    </Text>
                </span>
                <IconArrowRight className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover/story:opacity-100 group-focus-visible/story:opacity-100 motion-reduce:transition-none" />
            </span>
            <Text render={<h3 />} className="m-0 text-base font-medium text-balance">
                {story.title}
            </Text>
            <Text size="sm" variant="muted" render={<span />}>
                {story.summary}
            </Text>
            <span className="mt-2 flex items-center gap-4">
                <span className="flex shrink-0 items-baseline gap-1.5">
                    <Text size="xs" variant="muted" render={<span />}>
                        {story.metricLabel}
                    </Text>
                    <Text size="sm" render={<span />} className="font-medium" translate="no">
                        {story.metricValue}
                    </Text>
                    <TodayChange change={story.change} tone={story.tone} />
                </span>
                <span className="h-8 min-w-0 flex-1">
                    <Suspense fallback={<Skeleton className="h-full w-full" />}>
                        <TodaySparkline
                            values={story.series}
                            labels={story.seriesLabels}
                            tone={story.tone}
                            emphasizeLast={5}
                        />
                    </Suspense>
                </span>
            </span>
        </button>
    )
}
