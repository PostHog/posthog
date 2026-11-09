import { useMemo } from 'react'

import { ProportionBar, type Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import type { NewsChartItemApi } from 'products/today/frontend/generated/api.schemas'

const STORY_PARTS = 4

function storyParts(items: NewsChartItemApi[]): NewsChartItemApi[] {
    if (items.length <= STORY_PARTS) {
        return items
    }
    const rest = items.slice(STORY_PARTS - 1).reduce((total, item) => total + item.value, 0)
    return [...items.slice(0, STORY_PARTS - 1), { label: 'Other', value: rest }]
}

export function TodayNewsSplitChart({
    items,
    size,
}: {
    items: NewsChartItemApi[]
    size: 'lead' | 'story'
}): JSX.Element {
    const theme = useChartTheme()
    const series = useMemo<Series[]>(
        () =>
            (size === 'lead' ? items : storyParts(items)).map((item, index) => ({
                key: `part-${index}`,
                label: item.label,
                data: [item.value],
            })),
        [items, size]
    )
    return <ProportionBar series={series} theme={theme} config={{ legend: { interactive: false } }} />
}
