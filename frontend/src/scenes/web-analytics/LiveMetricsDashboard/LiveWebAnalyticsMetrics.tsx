import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { liveUserCountLogic } from 'lib/components/LiveUserCount/liveUserCountLogic'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { ChartDataPoint, DeviceBreakdownItem, PathItem } from './LiveWebAnalyticsMetricsTypes'
import { DeviceBreakdownChart, UsersPerMinuteChart } from './liveWebAnalyticsMetricsCharts'
import { liveWebAnalyticsMetricsLogic } from './liveWebAnalyticsMetricsLogic'

const STATS_POLL_INTERVAL_MS = 30000

const pathColumns: LemonTableColumns<PathItem> = [
    {
        title: 'Path',
        dataIndex: 'path',
        key: 'path',
        render: (_, record) => (
            <span className="font-mono text-xs truncate max-w-80 block" title={record.path}>
                {record.path}
            </span>
        ),
    },
    {
        title: 'Views',
        dataIndex: 'views',
        key: 'views',
        align: 'right',
        render: (_, record) => <span className="font-semibold">{record.views.toLocaleString()}</span>,
    },
]

const StatsHeader = ({
    liveUserCount,
    totalPageviews,
}: {
    liveUserCount: number | null
    totalPageviews: number
}): JSX.Element => {
    return (
        <div className="flex justify-between items-center mb-6">
            <div className="flex items-center gap-6">
                <div className="flex items-center gap-4">
                    <div className="flex flex-col">
                        <span className="text-muted text-xs uppercase font-medium">Users online</span>
                        <span className="text-2xl font-bold">
                            {liveUserCount !== null ? liveUserCount.toLocaleString() : '-'}
                        </span>
                    </div>
                    <div className="w-px h-10 bg-border" />
                    <div className="flex flex-col">
                        <span className="text-muted text-xs uppercase font-medium">Pageviews (30 min)</span>
                        <span className="text-2xl font-bold">{totalPageviews.toLocaleString()}</span>
                    </div>
                </div>
            </div>
        </div>
    )
}

const ChartsSection = ({
    chartData,
    deviceBreakdown,
    isLoading,
}: {
    chartData: ChartDataPoint[]
    deviceBreakdown: DeviceBreakdownItem[]
    isLoading: boolean
}): JSX.Element => {
    return (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
            <div className="md:col-span-2 bg-bg-light rounded-lg border p-4">
                <h3 className="text-sm font-semibold mb-4">Active users per minute</h3>
                {isLoading ? (
                    <div className="h-64 flex items-center justify-center">
                        <Spinner className="text-2xl" />
                    </div>
                ) : (
                    <div className="h-64">
                        <UsersPerMinuteChart data={chartData} />
                    </div>
                )}
            </div>
            <div className="bg-bg-light rounded-lg border p-4">
                <h3 className="text-sm font-semibold mb-4">Devices</h3>
                {isLoading ? (
                    <div className="h-64 flex items-center justify-center">
                        <Spinner className="text-2xl" />
                    </div>
                ) : (
                    <div className="h-64">
                        <DeviceBreakdownChart data={deviceBreakdown} />
                    </div>
                )}
            </div>
        </div>
    )
}

const PathsTable = ({ paths, isLoading }: { paths: PathItem[]; isLoading: boolean }): JSX.Element => {
    return (
        <div className="bg-bg-light rounded-lg border p-4">
            <h3 className="text-sm font-semibold mb-4">Top pages (last 30 minutes)</h3>
            {isLoading ? (
                <div className="space-y-2">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-8" />
                    ))}
                </div>
            ) : (
                <LemonTable
                    columns={pathColumns}
                    dataSource={paths}
                    rowKey="path"
                    size="small"
                    emptyState={
                        <div className="text-center py-6 text-muted">No pageviews recorded in the last 30 minutes</div>
                    }
                />
            )}
        </div>
    )
}

export const LiveWebAnalyticsMetrics = (): JSX.Element => {
    const { chartData, deviceBreakdown, topPaths, totalPageviews, isLoading } = useValues(liveWebAnalyticsMetricsLogic)
    const { liveUserCount } = useValues(liveUserCountLogic({ pollIntervalMs: STATS_POLL_INTERVAL_MS }))
    const { pauseStream, resumeStream } = useActions(liveUserCountLogic({ pollIntervalMs: STATS_POLL_INTERVAL_MS }))

    const { isVisible } = usePageVisibility()
    useEffect(() => {
        if (isVisible) {
            resumeStream()
        } else {
            pauseStream()
        }
    }, [isVisible, resumeStream, pauseStream])

    return (
        <div className="LivePageviews mt-4">
            <StatsHeader liveUserCount={liveUserCount} totalPageviews={totalPageviews} />
            <ChartsSection chartData={chartData} deviceBreakdown={deviceBreakdown} isLoading={isLoading} />
            <PathsTable paths={topPaths} isLoading={isLoading} />
        </div>
    )
}
