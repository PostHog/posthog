import { Text } from '@posthog/quill'

import { TodaySparkline } from 'scenes/project-homepage/today/TodaySparkline'

import type { BetsMetricApi } from '../generated/api.schemas'
import { metricPeriod, number } from '../lib/format'

export function BetsMetric({ metric, label }: { metric: BetsMetricApi; label?: string }): JSX.Element {
    const { unit } = metric
    const period = metricPeriod(metric.dates)
    return (
        <section className="flex min-w-0 items-center justify-between gap-6" aria-label={label ?? metric.name}>
            <div className="flex flex-col gap-1 min-w-0">
                <Text size="sm" variant="muted">
                    {label ?? metric.name}
                </Text>
                <span className="Bets__value tabular-nums">
                    {metric.current === null ? 'No data yet' : number(metric.current, unit)}
                </span>
                <Text size="xs" variant="muted">
                    {metric.change === null
                        ? metric.message || period
                        : `${metric.change > 0 ? '+' : ''}${number(metric.change)}% · ${period || 'over this period'}`}
                </Text>
            </div>
            {metric.values.length > 1 && (
                <div className="h-15 w-37.5 shrink-0">
                    <TodaySparkline
                        values={metric.values}
                        labels={metric.dates}
                        tone="neutral"
                        emphasizeLast={3}
                        formatValue={(value) => number(value, unit)}
                    />
                </div>
            )}
        </section>
    )
}
