import { Text } from '@posthog/quill'

import type { NewsOngoingStatusEnumApi, NewsOngoingStoryApi } from 'products/today/frontend/generated/api.schemas'

import { TodayNewsCard } from './TodayNewsCard'
import { TodayNewsKicker } from './TodayNewsKicker'
import type { TodayNewsRatedStory } from './todayNewsLogic'
import { TodayNewsSectionLabel } from './TodayNewsSectionLabel'
import { TodaySparkline } from './TodaySparkline'
import { useTodayTonePalette } from './todayTone'

const STATUS_LABEL: Record<NewsOngoingStatusEnumApi, string> = {
    worse: 'Worse',
    better: 'Better',
    same: 'No change',
    ended: 'Ended',
}

export function TodayNewsOngoing({
    items,
    rated,
    onDiveIn,
}: {
    items: NewsOngoingStoryApi[]
    rated: (item: NewsOngoingStoryApi, index: number) => TodayNewsRatedStory
    onDiveIn: (item: NewsOngoingStoryApi, index: number) => void
}): JSX.Element {
    const palette = useTodayTonePalette()
    return (
        <div className="flex flex-col gap-3">
            <TodayNewsSectionLabel>Ongoing</TodayNewsSectionLabel>
            <ul className="m-0 flex list-none flex-col p-0 [&>li+li]:border-t">
                {items.map((item, index) => (
                    <li key={item.id} className="flex py-4 first:pt-0 last:pb-0">
                        <TodayNewsCard
                            title={item.title}
                            rated={rated(item, index)}
                            onDiveIn={() => onDiveIn(item, index)}
                            className="gap-1"
                        >
                            <TodayNewsKicker
                                product={item.product}
                                productLabel={item.product_label}
                                tone={item.tone}
                            />
                            <Text size="sm" render={<span />} className="font-medium">
                                {item.title}
                            </Text>
                            <Text size="xs" variant="muted" render={<span />} className="text-pretty">
                                {item.update}
                            </Text>
                            <span className="flex items-center gap-2 pt-1">
                                <Text size="xs" render={<span />} className="flex gap-1 font-medium">
                                    <span
                                        // eslint-disable-next-line react/forbid-dom-props -- tone color comes from the Today palette
                                        style={item.status === 'same' ? undefined : { color: palette[item.tone] }}
                                    >
                                        {STATUS_LABEL[item.status]}
                                    </span>
                                    {item.status === 'ended' ? null : (
                                        <span className="text-muted-foreground">
                                            · day <span translate="no">{item.day}</span>
                                        </span>
                                    )}
                                </Text>
                                {item.series.length > 1 ? (
                                    <span className="ms-auto h-5 w-20 shrink-0">
                                        <TodaySparkline
                                            values={item.series}
                                            labels={item.series_labels}
                                            tone={item.tone}
                                            emphasizeLast={1}
                                            fromZero
                                        />
                                    </span>
                                ) : null}
                            </span>
                        </TodayNewsCard>
                    </li>
                ))}
            </ul>
        </div>
    )
}
