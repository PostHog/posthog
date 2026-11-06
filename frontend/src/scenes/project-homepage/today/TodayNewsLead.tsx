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
    const hasChart = story.series.length > 1

    return (
        <button
            type="button"
            onClick={onDiveIn}
            aria-label={`Dive in: ${story.title}`}
            className="group/story -m-3 grid cursor-pointer gap-6 rounded-lg p-3 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 @3xl:grid-cols-2"
            data-attr="today-news-dive-in"
        >
            <span className="flex flex-col gap-2">
                <TodayNewsKicker story={story} />
                <Heading size="xl" render={<h3 />} className="m-0">
                    {story.title}
                </Heading>
                <Text size="sm" variant="muted" render={<p />} className="m-0 text-pretty">
                    {story.summary}
                </Text>
                <Text size="xs" render={<span />} className="mt-auto flex items-center gap-1 pt-2 font-medium">
                    Dive in
                    <IconArrowRight className="size-3.5 transition-transform group-hover/story:translate-x-0.5 motion-reduce:transition-none" />
                </Text>
            </span>
            {hasChart ? (
                <span className="flex min-h-36 flex-col gap-1">
                    <Text size="xs" variant="muted" render={<span />} className="flex min-h-6 items-center gap-1">
                        {story.metric_label}
                        {story.metric_value ? (
                            <>
                                <span aria-hidden>·</span>
                                <span className="font-medium text-foreground" translate="no">
                                    {story.metric_value}
                                </span>
                            </>
                        ) : null}
                    </Text>
                    <span className="min-h-28 flex-1">
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
        </button>
    )
}
