import { Suspense, lazy } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Heading, Skeleton, Text } from '@posthog/quill'

import { retryImport } from 'lib/utils/retryImport'

import type { NewsLeadStoryApi } from 'products/today/frontend/generated/api.schemas'

import { TodayNewsKicker } from './TodayNewsKicker'

const TodaySparkline = lazy(() =>
    retryImport(() => import('./TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

export function TodayNewsLead({ story, onDiveIn }: { story: NewsLeadStoryApi; onDiveIn: () => void }): JSX.Element {
    return (
        <button
            type="button"
            onClick={onDiveIn}
            aria-label={`Dive in: ${story.title}`}
            className="group/story -m-2 flex cursor-pointer flex-col gap-2 rounded-md p-2 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
            data-attr="today-news-dive-in"
        >
            <TodayNewsKicker story={story} />
            <Heading size="xl" render={<h3 />} className="m-0">
                {story.title}
            </Heading>
            <Text size="sm" variant="muted" render={<p />} className="m-0 text-pretty">
                {story.summary}
            </Text>
            {story.series.length > 1 ? (
                <span className="mt-2 flex flex-col gap-1">
                    <Text size="xs" variant="muted" render={<span />}>
                        {story.metric_label}
                        {story.metric_value ? (
                            <>
                                {' · '}
                                <span className="font-medium text-foreground" translate="no">
                                    {story.metric_value}
                                </span>
                            </>
                        ) : null}
                    </Text>
                    <span className="h-24">
                        <Suspense fallback={<Skeleton className="h-full w-full" />}>
                            <TodaySparkline
                                values={story.series}
                                labels={story.series_labels}
                                tone={story.tone}
                                emphasizeLast={5}
                                fromZero
                            />
                        </Suspense>
                    </span>
                </span>
            ) : null}
            <Text size="xs" render={<span />} className="mt-1 flex items-center gap-1 font-medium">
                Dive in
                <IconArrowRight className="size-3.5 transition-transform group-hover/story:translate-x-0.5 motion-reduce:transition-none" />
            </Text>
        </button>
    )
}
