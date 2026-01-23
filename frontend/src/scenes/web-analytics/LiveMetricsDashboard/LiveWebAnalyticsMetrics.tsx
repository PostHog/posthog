import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { liveUserCountLogic } from 'lib/components/LiveUserCount/liveUserCountLogic'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'

import { LiveChartCard } from './LiveChartCard'
import { LiveStatCard, LiveStatDivider } from './LiveStatCard'
import { LiveTopPathsTable } from './LiveTopPathsTable'
import { LiveWorldMap } from './LiveWorldMap'
import { DeviceBreakdownChart, UsersPerMinuteChart } from './liveWebAnalyticsMetricsCharts'
import { liveWebAnalyticsMetricsLogic } from './liveWebAnalyticsMetricsLogic'

const STATS_POLL_INTERVAL_MS = 1000

export const LiveWebAnalyticsMetrics = (): JSX.Element => {
    const {
        chartData,
        deviceBreakdown,
        countryBreakdown,
        topPaths,
        totalPageviews,
        totalUniqueVisitors,
        totalDevices,
        isLoading,
    } = useValues(liveWebAnalyticsMetricsLogic)
    const { pauseStream, resumeStream } = useActions(liveWebAnalyticsMetricsLogic)
    const { liveUserCount } = useValues(liveUserCountLogic({ pollIntervalMs: STATS_POLL_INTERVAL_MS }))
    const { pauseStream: pauseLiveCount, resumeStream: resumeLiveCount } = useActions(
        liveUserCountLogic({ pollIntervalMs: STATS_POLL_INTERVAL_MS })
    )

    const { isVisible } = usePageVisibility()
    useEffect(() => {
        if (isVisible) {
            resumeStream()
            resumeLiveCount()
        } else {
            pauseStream()
            pauseLiveCount()
        }
    }, [isVisible, resumeStream, pauseStream, resumeLiveCount, pauseLiveCount])

    const timezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, [])

    return (
        <div className="LivePageviews mt-4">
            <div className="flex flex-wrap items-center gap-4 md:gap-6 mb-6">
                <LiveStatCard label="Users online" value={liveUserCount} />
                <LiveStatDivider />
                <LiveStatCard label="Unique visitors (30 min)" value={totalUniqueVisitors} isLoading={isLoading} />
                <LiveStatDivider />
                <LiveStatCard label="Pageviews (30 min)" value={totalPageviews} isLoading={isLoading} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
                <LiveChartCard
                    title="Active users per minute"
                    subtitle={timezone}
                    subtitleTooltip="Metrics are shown in your local timezone"
                    isLoading={isLoading}
                    className="md:col-span-2"
                >
                    <UsersPerMinuteChart data={chartData} />
                </LiveChartCard>

                <LiveChartCard title="Devices" isLoading={isLoading} contentClassName="h-48 md:h-64">
                    <DeviceBreakdownChart data={deviceBreakdown} totalDevices={totalDevices} />
                </LiveChartCard>
            </div>

            <LiveTopPathsTable paths={topPaths} isLoading={isLoading} />

            <LiveChartCard title="Countries" isLoading={isLoading} contentClassName="aspect-[2.3/1] mt-6">
                <LiveWorldMap
                    data={countryBreakdown}
                    totalEvents={countryBreakdown.reduce((sum: number, c: { count: number }) => sum + c.count, 0)}
                />
            </LiveChartCard>
        </div>
    )
}
