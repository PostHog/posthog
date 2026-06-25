import { IconArrowRight, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

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

export function WebAnalyticsDigestNotification({
    metadata,
    onOpen,
    onAskMax,
}: {
    metadata: WebAnalyticsDigestMetadata
    onOpen: (e: React.MouseEvent) => void
    onAskMax: (e: React.MouseEvent) => void
}): JSX.Element {
    const byKey = (key: string): WebAnalyticsDigestMetric | undefined => metadata.metrics.find((m) => m.key === key)
    const hero = byKey('visitors')
    const pageviews = byKey('pageviews')
    const sessions = byKey('sessions')
    const subline = [pageviews, sessions]
        .filter((metric): metric is WebAnalyticsDigestMetric => Boolean(metric))
        .map((metric) => `${metric.value} ${metric.label.toLowerCase()}`)
        .join(' · ')

    return (
        <div className="mt-1 flex flex-col gap-2.5">
            {hero && (
                <div className="flex items-baseline gap-2">
                    <span className="text-3xl font-bold leading-none tabular-nums">{hero.value}</span>
                    <span className="text-sm text-secondary">{hero.label.toLowerCase()}</span>
                    <TrendPill change={hero.change} />
                </div>
            )}
            {subline && <div className="text-xs text-muted">{subline}</div>}
            <div className="flex flex-col gap-1.5">
                <LemonButton
                    type="primary"
                    size="small"
                    fullWidth
                    center
                    sideIcon={<IconArrowRight />}
                    onClick={onOpen}
                >
                    View web analytics
                </LemonButton>
                <LemonButton type="secondary" size="small" fullWidth center icon={<IconSparkles />} onClick={onAskMax}>
                    Ask PostHog AI
                </LemonButton>
            </div>
        </div>
    )
}
