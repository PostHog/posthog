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
                <Text size="sm" variant="muted">
                    {story.productLabel}
                </Text>
            </span>
            <Text render={<h3 />} className="m-0 text-xl font-semibold text-balance">
                {story.title}
            </Text>
            <Text size="sm" variant="muted" render={<p />} className="m-0">
                {story.summary}
            </Text>
            <div className="mt-2 flex flex-col gap-1 rounded-lg border p-4">
                <Text size="sm" variant="muted">
                    {story.metricLabel}
                </Text>
                <span className="flex items-baseline gap-2">
                    <span className="text-2xl font-semibold" translate="no">
                        {story.metricValue}
                    </span>
                    <TodayChange change={story.change} tone={story.tone} />
                </span>
                <div className="mt-2 h-30">
                    <Suspense fallback={<Skeleton className="h-full w-full" />}>
                        <TodaySparkline
                            values={story.series}
                            labels={story.seriesLabels}
                            tone={story.tone}
                            emphasizeLast={5}
                        />
                    </Suspense>
                </div>
            </div>
            <div className="mt-2">
                <Button variant="outline" onClick={onDiveIn} data-attr="today-news-dive-in">
                    Dive in
                    <IconArrowRight />
                </Button>
            </div>
        </article>
    )
}
