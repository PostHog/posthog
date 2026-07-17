import { WebAnalyticsDigestMetadata, WebAnalyticsDigestMetric, WebAnalyticsDigestMetricChange } from '~/types'

function TrendPill({ change }: { change: WebAnalyticsDigestMetricChange | null }): JSX.Element | null {
    if (!change) {
        return null
    }
    const colorClass = change.is_good ? 'text-success' : 'text-danger'
    return (
        <span className={`inline-flex items-center gap-0.5 text-xs font-semibold ${colorClass}`}>
            <span className="leading-none">{change.direction === 'Up' ? '↑' : '↓'}</span>
            {change.percent}%
        </span>
    )
}

export function WebAnalyticsDigestNotification({ metadata }: { metadata: WebAnalyticsDigestMetadata }): JSX.Element {
    const byKey = (key: string): WebAnalyticsDigestMetric | undefined => metadata.metrics.find((m) => m.key === key)
    const hero = byKey('visitors')
    const pageviews = byKey('pageviews')
    const sessions = byKey('sessions')
    const subline = [pageviews, sessions]
        .filter((metric): metric is WebAnalyticsDigestMetric => Boolean(metric))
        .map((metric) => `${metric.value} ${metric.label.toLowerCase()}`)
        .join(' · ')

    return (
        <div className="mt-2 flex flex-col gap-1.5">
            {hero && (
                <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <span className="text-lg font-bold leading-none tabular-nums">{hero.value}</span>
                    {/* Keep label + trend together so the pill wraps below the number instead of clipping the panel edge */}
                    <span className="inline-flex items-baseline gap-2 whitespace-nowrap">
                        <span className="text-sm text-secondary">{hero.label.toLowerCase()}</span>
                        <TrendPill change={hero.change} />
                    </span>
                </div>
            )}
            {subline && <div className="text-xs text-secondary">{subline}</div>}
        </div>
    )
}
