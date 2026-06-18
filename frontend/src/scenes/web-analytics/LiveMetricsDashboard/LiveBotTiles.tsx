import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { usePageVisibility } from 'lib/hooks/usePageVisibility'

import { LiveBotTrafficCard } from './LiveBotTrafficCard'
import { LiveChartCard } from './LiveChartCard'
import { LiveStatCard, LiveStatDivider } from './LiveStatCard'
import { BotEventsPerMinuteChart } from './liveWebAnalyticsMetricsCharts'
import { liveWebAnalyticsMetricsLogic } from './liveWebAnalyticsMetricsLogic'

export const LiveBotTiles = (): JSX.Element => {
    const { chartData, botBreakdown, totalBotEvents, totalBotEligibleEvents, isLoading } =
        useValues(liveWebAnalyticsMetricsLogic)
    const { pauseStream, resumeStream } = useActions(liveWebAnalyticsMetricsLogic)

    const { isVisible } = usePageVisibility()
    useEffect(() => {
        if (isVisible) {
            resumeStream()
        } else {
            pauseStream()
        }
    }, [isVisible, resumeStream, pauseStream])

    const timezone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, [])
    const botShare = totalBotEligibleEvents > 0 ? Math.round((totalBotEvents / totalBotEligibleEvents) * 100) : null

    return (
        <div className="mb-6">
            <div className="flex flex-wrap items-center gap-4 md:gap-6 mb-6">
                <LiveStatCard label="Bot events" value={totalBotEvents} isLoading={isLoading} />
                <LiveStatDivider />
                <LiveStatCard label="Total events" value={totalBotEligibleEvents} isLoading={isLoading} />
                <LiveStatDivider />
                <LiveStatCard label="Bot share %" value={botShare} isLoading={isLoading} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <LiveChartCard
                    title="Bot requests per minute"
                    subtitle={timezone}
                    subtitleTooltip="Metrics are shown in your local timezone"
                    isLoading={isLoading}
                    contentClassName="h-64 md:h-80"
                >
                    <BotEventsPerMinuteChart data={chartData} />
                </LiveChartCard>
                <LiveBotTrafficCard
                    data={botBreakdown}
                    totalBotEvents={totalBotEvents}
                    totalEvents={totalBotEligibleEvents}
                    isLoading={isLoading}
                />
            </div>
        </div>
    )
}
