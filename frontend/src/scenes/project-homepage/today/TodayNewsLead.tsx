import { Suspense, lazy } from 'react'

import { Skeleton } from '@posthog/quill'

import { retryImport } from 'lib/utils/retryImport'

import { TodayChange } from './TodayChange'
import type { TodayNewsLeadStory } from './todayNewsEdition'
import { TodayNewsKicker } from './TodayNewsKicker'

const TodaySparkline = lazy(() =>
    retryImport(() => import('./TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

export function TodayNewsLead({ story, onDiveIn }: { story: TodayNewsLeadStory; onDiveIn: () => void }): JSX.Element {
    return (
        <button
            type="button"
            onClick={onDiveIn}
            aria-label={`Dive in: ${story.title}`}
            className="group/story flex h-full w-full cursor-pointer flex-col gap-3 rounded-sm text-start focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30"
            data-attr="today-news-dive-in"
        >
            <TodayNewsKicker story={story} showChange={false} />
            <h3 className="m-0 text-3xl leading-tight font-bold tracking-tight text-balance decoration-2 underline-offset-4 group-hover/story:underline">
                {story.title}
            </h3>
            <p className="m-0 text-base text-pretty text-muted-foreground">{story.summary}</p>
            <figure className="m-0 mt-2 flex min-h-40 flex-1 flex-col gap-3">
                <figcaption className="flex items-baseline justify-between gap-4 border-t pt-2 font-mono text-xs tracking-wide text-muted-foreground uppercase">
                    <span className="flex items-baseline gap-2">
                        <span>{story.metricLabel}</span>
                        <span className="text-foreground" translate="no">
                            {story.metricValue}
                        </span>
                        <TodayChange change={story.change} tone={story.tone} />
                    </span>
                    <span className="text-foreground group-hover/story:underline">Dive in</span>
                </figcaption>
                <span className="min-h-28 flex-1">
                    <Suspense fallback={<Skeleton className="h-full w-full" />}>
                        <TodaySparkline
                            values={story.series}
                            labels={story.seriesLabels}
                            tone={story.tone}
                            emphasizeLast={5}
                        />
                    </Suspense>
                </span>
            </figure>
        </button>
    )
}
