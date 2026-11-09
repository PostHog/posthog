import { Heading, Text, cn } from '@posthog/quill'

import type { NewsLeadStoryApi } from 'products/today/frontend/generated/api.schemas'

import { TodayNewsCard } from './TodayNewsCard'
import { TodayNewsChart } from './TodayNewsChart'
import { TodayNewsKicker } from './TodayNewsKicker'
import { leadChart, leadHasChart } from './todayNewsLayout'
import type { TodayNewsRatedStory } from './todayNewsLogic'
import { TodaySparkline } from './TodaySparkline'

export function TodayNewsLead({
    story,
    stacked,
    rated,
    onDiveIn,
}: {
    story: NewsLeadStoryApi
    stacked: boolean
    rated: TodayNewsRatedStory
    onDiveIn: () => void
}): JSX.Element {
    const chart = leadChart(story)

    return (
        <TodayNewsCard
            title={story.title}
            rated={rated}
            onDiveIn={onDiveIn}
            className={cn('grid gap-6', leadHasChart(story) && !stacked && '@3xl:grid-cols-2')}
        >
            <span className="flex flex-col gap-2">
                <TodayNewsKicker
                    product={story.product}
                    productLabel={story.product_label}
                    change={story.change}
                    tone={story.tone}
                />
                <Heading size={stacked ? '2xl' : 'xl'} render={<h3 />} className="m-0">
                    {story.title}
                </Heading>
                <Text size="sm" variant="muted" render={<p />} className="m-0 text-pretty">
                    {story.summary}
                </Text>
            </span>
            {chart ? (
                <span className="flex min-h-36 flex-col justify-center gap-1">
                    <TodayNewsChart chart={chart} tone={story.tone} size="lead" />
                </span>
            ) : story.series.length > 1 ? (
                <span className="flex min-h-36 flex-col gap-1">
                    <Text size="xs" variant="muted" render={<span />} className="flex min-h-6 items-center gap-1">
                        <span>{story.metric_label}</span>
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
                        <TodaySparkline
                            values={story.series}
                            labels={story.series_labels}
                            tone={story.tone}
                            emphasizeLast={5}
                            fromZero
                        />
                    </span>
                </span>
            ) : null}
        </TodayNewsCard>
    )
}
