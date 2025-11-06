import { useValues } from 'kea'

import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyDuration } from 'lib/utils'

import { sessionProfileLogic } from '../sessionProfileLogic'

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

export function SessionMetricsCard(): JSX.Element {
    const { sessionData, sessionDuration, uniqueUrlCount, totalEventCount, otherEventCount, isInitialLoading } =
        useValues(sessionProfileLogic)
    return (
        <div className="@container">
            <div className="flex flex-col @md:flex-row gap-4 @md:justify-between">
                <MetricCard
                    title="Duration"
                    value={sessionDuration !== null ? humanFriendlyDuration(sessionDuration) : null}
                    subtitle={sessionDuration !== null ? `${sessionDuration} seconds` : undefined}
                    isLoading={isInitialLoading}
                />
                <MetricCard title="Unique URLs" value={uniqueUrlCount} isLoading={isInitialLoading} />
                <MetricCard
                    title="Total Events"
                    value={totalEventCount}
                    subtitle={
                        sessionData?.pageview_count !== undefined &&
                        sessionData?.autocapture_count !== undefined &&
                        sessionData?.screen_count !== undefined
                            ? `${sessionData.pageview_count} pageviews, ${sessionData.autocapture_count} autocapture, ${sessionData.screen_count} screens${
                                  otherEventCount > 0 ? ` + ${otherEventCount} other` : ''
                              }`
                            : undefined
                    }
                    isLoading={isInitialLoading}
                />
            </div>
        </div>
    )
}
