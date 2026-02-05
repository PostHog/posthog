import clsx from 'clsx'
import { useLayoutEffect, useRef } from 'react'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { PathItem } from './LiveWebAnalyticsMetricsTypes'

const ROW_HEIGHT = 36

interface AnimatedPathRowProps {
    item: PathItem
    offset: number
    positionDelta: number
    deltaVersion: number
    percentage: number
}

const AnimatedPathRow = ({
    item,
    offset,
    positionDelta,
    deltaVersion,
    percentage,
}: AnimatedPathRowProps): JSX.Element => {
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
            <div className="flex items-center gap-2 min-w-0 flex-1 mr-4">
                <Tooltip title={item.path} delayMs={300}>
                    <span className="font-mono text-xs truncate">{item.path}</span>
                </Tooltip>
                {positionDelta !== 0 && (
                    <span
                        key={`${positionDelta}-${deltaVersion}`}
                        className={clsx(
                            'flex items-center text-xs font-semibold animate-fade-out-delayed flex-shrink-0',
                            positionDelta < 0 ? 'text-success' : 'text-danger'
                        )}
                    >
                        {positionDelta < 0 ? '↑' : '↓'}
                        {Math.abs(positionDelta)}
                    </span>
                )}
            </div>
            <div className="flex items-center justify-center gap-1 flex-shrink-0 w-28">
                <span className="font-semibold text-sm tabular-nums">{item.views.toLocaleString()}</span>
                <span className="text-muted text-xs tabular-nums">({percentage.toFixed(1)}%)</span>
            </div>
        </div>
    )
}

interface LiveTopPathsTableProps {
    paths: PathItem[]
    isLoading: boolean
    totalPageviews: number
}

export const LiveTopPathsTable = ({ paths, isLoading, totalPageviews }: LiveTopPathsTableProps): JSX.Element => {
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
                    <div className="flex items-center px-3 py-2 border-b text-xs font-semibold text-muted uppercase">
                        <span className="flex-1">Path</span>
                        <span className="w-28 text-center">Views</span>
                    </div>
                    <div className="relative" style={{ height: paths.length * ROW_HEIGHT }}>
                        {paths.map((item, index) => (
                            <AnimatedPathRow
                                key={item.path}
                                item={item}
                                offset={index * ROW_HEIGHT}
                                positionDelta={positionDeltas.get(item.path) ?? 0}
                                deltaVersion={deltaVersionRef.current}
                                percentage={totalPageviews > 0 ? (item.views / totalPageviews) * 100 : 0}
                            />
                        ))}
                    </div>
                </>
            )}
        </div>
    )
}
