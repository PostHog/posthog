import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { liveUserCountLogic } from 'lib/components/LiveUserCount/liveUserCountLogic'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'

import { BreakdownLiveCard } from './BreakdownLiveCard'
import { LiveChartCard } from './LiveChartCard'
import { LiveStatCard, LiveStatDivider } from './LiveStatCard'
import { LiveTopPathsTable } from './LiveTopPathsTable'
import { BrowserBreakdownItem, DeviceBreakdownItem } from './LiveWebAnalyticsMetricsTypes'
import { getBrowserLogo } from './browserLogos'
import { UsersPerMinuteChart } from './liveWebAnalyticsMetricsCharts'
import { liveWebAnalyticsMetricsLogic } from './liveWebAnalyticsMetricsLogic'

const STATS_POLL_INTERVAL_MS = 1000

export const LiveWebAnalyticsMetrics = (): JSX.Element => {
    const {
        chartData,
        deviceBreakdown,
        browserBreakdown,
        topPaths,
        totalPageviews,
        totalUniqueVisitors,
        totalBrowsers,
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
                <LiveStatCard label="Unique visitors" value={totalUniqueVisitors} isLoading={isLoading} />
                <LiveStatDivider />
                <LiveStatCard label="Pageviews" value={totalPageviews} isLoading={isLoading} />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                <LiveChartCard
                    title="Active users per minute"
                    subtitle={timezone}
                    subtitleTooltip="Metrics are shown in your local timezone"
                    isLoading={isLoading}
                    contentClassName="h-64 md:h-80"
                >
                    <UsersPerMinuteChart data={chartData} />
                </LiveChartCard>

                <LiveTopPathsTable paths={topPaths} isLoading={isLoading} totalPageviews={totalPageviews} />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
                <BreakdownLiveCard<DeviceBreakdownItem>
                    title="Devices"
                    data={deviceBreakdown}
                    getKey={(d) => d.device}
                    getLabel={(d) => d.device}
                    emptyMessage="No device data"
                    statLabel="unique devices"
                    isLoading={isLoading}
                />
                <BreakdownLiveCard<BrowserBreakdownItem>
                    title="Browsers"
                    data={browserBreakdown}
                    getKey={(d) => d.browser}
                    getLabel={(d) => d.browser}
                    renderIcon={(d) => {
                        const Logo = getBrowserLogo(d.browser)
                        return <Logo className="w-4 h-4 flex-shrink-0" />
                    }}
                    emptyMessage="No browser data"
                    statLabel="unique browsers"
                    totalCount={totalBrowsers}
                    isLoading={isLoading}
                />
            </div>
        </div>
    )
}
