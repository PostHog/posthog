import { Suspense, lazy } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { Button, IconStack, IconStackItem, Skeleton, Text } from '@posthog/quill'

import { retryImport } from 'lib/utils/retryImport'

import { TodayChange } from './TodayChange'
import type { TodayNewsLeadStory } from './todayNewsEdition'
import { productIcon } from './todayRowIcons'

const TodaySparkline = lazy(() =>
    retryImport(() => import('./TodaySparkline').then((m) => ({ default: m.TodaySparkline })))
)

export function TodayNewsLead({ story, onDiveIn }: { story: TodayNewsLeadStory; onDiveIn: () => void }): JSX.Element {
    const icon = productIcon(story.product)

    return (
        <article className="flex flex-col gap-2">
            <span className="flex items-center gap-2">
                <IconStack className="TodayRow__icons">
                    <IconStackItem color={icon.color}>{icon.glyph}</IconStackItem>
                </IconStack>
                <Text size="xs" variant="muted" render={<span />}>
                    {story.productLabel}
                </Text>
            </span>
            <Text render={<h3 />} className="m-0 text-xl font-semibold text-balance">
                {story.title}
            </Text>
            <Text size="sm" variant="muted" render={<p />} className="m-0">
                {story.summary}
            </Text>
            <div className="mt-1">
                <Button variant="outline" onClick={onDiveIn} data-attr="today-news-dive-in">
                    Dive in
                    <IconArrowRight />
                </Button>
            </div>
            <div className="mt-3 flex min-h-44 flex-1 flex-col rounded-lg border bg-card p-4">
                <Text size="xs" variant="muted" render={<span />}>
                    {story.metricLabel}
                </Text>
                <span className="flex items-baseline gap-2">
                    <span className="text-2xl font-semibold" translate="no">
                        {story.metricValue}
                    </span>
                    <TodayChange change={story.change} tone={story.tone} />
                </span>
                <div className="mt-3 min-h-16 flex-1">
                    <Suspense fallback={<Skeleton className="h-full w-full" />}>
                        <TodaySparkline
                            values={story.series}
                            labels={story.seriesLabels}
                            tone={story.tone}
                            emphasizeLast={5}
                        />
                    </Suspense>
                </div>
                <span className="mt-1 flex justify-between">
                    <Text size="xs" variant="muted" render={<span />}>
                        {story.seriesLabels[0]}
                    </Text>
                    <Text size="xs" variant="muted" render={<span />}>
                        {story.seriesLabels[story.seriesLabels.length - 1]}
                    </Text>
                </span>
            </div>
        </article>
    )
}
