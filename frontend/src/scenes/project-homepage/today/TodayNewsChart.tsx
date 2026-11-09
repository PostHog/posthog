import { Text } from '@posthog/quill'

import type { NewsChartApi } from 'products/today/frontend/generated/api.schemas'

import { TodayNewsGroupedBarsChart } from './TodayNewsGroupedBarsChart'
import { TodayNewsSplitChart } from './TodayNewsSplitChart'
import { TodaySparkline } from './TodaySparkline'
import type { TodayTone } from './todayTone'

export function TodayNewsChart({
    chart,
    tone,
    size,
}: {
    chart: NewsChartApi
    tone: TodayTone
    size: 'lead' | 'story'
}): JSX.Element | null {
    if (chart.kind === 'line' && chart.values.length < 2) {
        return null
    }
    return (
        <span className="flex w-full flex-col gap-1">
            {chart.caption ? (
                <Text
                    size="xs"
                    variant="muted"
                    render={<span />}
                    className={size === 'lead' ? 'flex min-h-6 items-center' : 'truncate'}
                    title={size === 'story' ? chart.caption : undefined}
                >
                    {chart.caption}
                </Text>
            ) : null}
            {chart.kind === 'line' ? (
                <span className={size === 'lead' ? 'min-h-28 flex-1' : 'h-12'}>
                    <TodaySparkline
                        values={chart.values}
                        labels={chart.labels}
                        tone={tone}
                        emphasizeLast={size === 'lead' ? 5 : 3}
                        fromZero
                    />
                </span>
            ) : chart.kind === 'split' ? (
                <TodayNewsSplitChart items={chart.items} size={size} />
            ) : (
                <TodayNewsGroupedBarsChart items={chart.items} higherIsGood={chart.higher_is_good} size={size} />
            )}
        </span>
    )
}
