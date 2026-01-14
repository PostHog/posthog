import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useLayoutEffect, useRef } from 'react'

import { LemonSkeleton, Spinner } from '@posthog/lemon-ui'

import { liveUserCountLogic } from 'lib/components/LiveUserCount/liveUserCountLogic'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'

import { ChartDataPoint, DeviceBreakdownItem, PathItem } from './LiveWebAnalyticsMetricsTypes'
import { DeviceBreakdownChart, UsersPerMinuteChart } from './liveWebAnalyticsMetricsCharts'
import { liveWebAnalyticsMetricsLogic } from './liveWebAnalyticsMetricsLogic'

const STATS_POLL_INTERVAL_MS = 30000
const ROW_HEIGHT = 36

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

const AnimatedPathRow = ({
    item,
    offset,
    positionDelta,
    deltaVersion,
}: {
    item: PathItem
    offset: number
    positionDelta: number
    deltaVersion: number
}): JSX.Element => {
    const currentOffsetRef = useRef(offset)
    const shouldSkipAnimation = currentOffsetRef.current === offset

    useLayoutEffect(() => {
        currentOffsetRef.current = offset
    }, [offset])

    return (
        <div
            className={clsx(
                'flex items-center justify-between px-3 absolute w-full left-0 ease-out border-b border-border',
                shouldSkipAnimation ? 'duration-0' : 'transition-transform duration-500'
            )}
            style={{
                height: ROW_HEIGHT,
                transform: `translateY(${offset}px)`,
            }}
        >
            <div className="flex items-center gap-2">
                <span className="font-mono text-xs truncate max-w-72" title={item.path}>
                    {item.path}
                </span>
                {positionDelta !== 0 && (
                    <span
                        key={`${positionDelta}-${deltaVersion}`}
                        className={clsx(
                            'flex items-center text-xs font-semibold animate-fade-out-delayed',
                            positionDelta < 0 ? 'text-success' : 'text-danger'
                        )}
                    >
                        {positionDelta < 0 ? '↑' : '↓'}
                        {Math.abs(positionDelta)}
                    </span>
                )}
            </div>
            <span className="font-semibold text-sm">{item.views.toLocaleString()}</span>
        </div>
    )
}

const PathsTable = ({ paths, isLoading }: { paths: PathItem[]; isLoading: boolean }): JSX.Element => {
    const prevPositionsRef = useRef<Map<string, number>>(new Map())
    const deltaVersionRef = useRef(0)

    const positionDeltas = new Map<string, number>()
    paths.forEach((item, index) => {
        const prevPosition = prevPositionsRef.current.get(item.path)
        if (prevPosition !== undefined && prevPosition !== index) {
            positionDeltas.set(item.path, index - prevPosition)
        }
    })

    if (positionDeltas.size > 0) {
        deltaVersionRef.current++
    }

    useLayoutEffect(() => {
        prevPositionsRef.current = new Map(paths.map((item, index) => [item.path, index]))
    }, [paths])

    return (
        <div className="bg-bg-light rounded-lg border p-4">
            <h3 className="text-sm font-semibold mb-4">Top pages (last 30 minutes)</h3>
            {isLoading ? (
                <div className="space-y-2">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-8" />
                    ))}
                </div>
            ) : paths.length === 0 ? (
                <div className="text-center py-6 text-muted">No pageviews recorded in the last 30 minutes</div>
            ) : (
                <>
                    <div className="flex items-center justify-between px-3 py-2 border-b text-xs font-semibold text-muted uppercase">
                        <span>Path</span>
                        <span>Views</span>
                    </div>
                    <div className="relative" style={{ height: paths.length * ROW_HEIGHT }}>
                        {paths.map((item, index) => (
                            <AnimatedPathRow
                                key={item.path}
                                item={item}
                                offset={index * ROW_HEIGHT}
                                positionDelta={positionDeltas.get(item.path) ?? 0}
                                deltaVersion={deltaVersionRef.current}
                            />
                        ))}
                    </div>
                </>
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
