import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils'

interface MetricCardProps {
    title: string
    value: string | number | null
    isLoading?: boolean
    subtitle?: string
}

function MetricCard({ title, value, isLoading, subtitle }: MetricCardProps): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="p-4 flex flex-col flex-1 justify-between max-w-80 min-h-36">
            <div>
                <div className="text-sm font-semibold text-muted-alt mb-1">{title}</div>
                {isLoading ? (
                    <LemonSkeleton className="h-8 w-24" />
                ) : (
                    <>
                        <div className="text-3xl font-bold text-primary my-2 truncate">{value ?? '-'}</div>
                        {subtitle && <div className="text-xs text-muted">{subtitle}</div>}
                    </>
                )}
            </div>
        </LemonCard>
    )
}

export interface SessionMetricsCardProps {
    duration: number | null
    uniqueUrlCount: number
    totalEventCount: number
    pageviewCount?: number
    autocaptureCount?: number
    screenCount?: number
    otherEventCount?: number
    isLoading?: boolean
}

export function SessionMetricsCard({
    duration,
    uniqueUrlCount,
    totalEventCount,
    pageviewCount,
    autocaptureCount,
    screenCount,
    otherEventCount = 0,
    isLoading,
}: SessionMetricsCardProps): JSX.Element {
    return (
        <div className="@container">
            <div className="grid grid-cols-1 @md:grid-cols-3 gap-4">
                <MetricCard
                    title="Duration"
                    value={duration !== null ? humanFriendlyDuration(duration) : null}
                    subtitle={duration !== null ? `${duration} seconds` : undefined}
                    isLoading={isLoading}
                />
                <MetricCard title="Unique URLs" value={uniqueUrlCount} isLoading={isLoading} />
                <MetricCard
                    title="Total Events"
                    value={totalEventCount}
                    subtitle={
                        pageviewCount !== undefined && autocaptureCount !== undefined && screenCount !== undefined
                            ? `${pageviewCount} pageviews, ${autocaptureCount} autocapture, ${screenCount} screens${
                                  otherEventCount > 0 ? ` + ${otherEventCount} other` : ''
                              }`
                            : undefined
                    }
                    isLoading={isLoading}
                />
            </div>
        </div>
    )
}
