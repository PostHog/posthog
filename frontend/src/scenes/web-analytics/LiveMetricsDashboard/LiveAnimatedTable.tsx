import clsx from 'clsx'
import { ReactNode, useLayoutEffect, useRef } from 'react'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

const ROW_HEIGHT = 36

interface AnimatedRowProps {
    label: ReactNode
    tooltipTitle: string
    views: number
    offset: number
    positionDelta: number
    deltaVersion: number
    percentage: number
}

const AnimatedRow = ({
    label,
    tooltipTitle,
    views,
    offset,
    positionDelta,
    deltaVersion,
    percentage,
}: AnimatedRowProps): JSX.Element => {
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
                <Tooltip title={tooltipTitle} delayMs={300}>
                    {label}
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
                <span className="font-semibold text-sm tabular-nums">{views.toLocaleString()}</span>
                <span className="text-muted text-xs tabular-nums">({percentage.toFixed(1)}%)</span>
            </div>
        </div>
    )
}

interface LiveAnimatedTableProps<T> {
    items: T[]
    keyExtractor: (item: T) => string
    viewsExtractor: (item: T) => number
    renderLabel: (item: T) => { node: ReactNode; tooltipTitle: string }
    title: string
    columnLabel: string
    emptyMessage: string
    isLoading: boolean
    totalPageviews: number
    className?: string
}

export function LiveAnimatedTable<T>({
    items,
    keyExtractor,
    viewsExtractor,
    renderLabel,
    title,
    columnLabel,
    emptyMessage,
    isLoading,
    totalPageviews,
    className,
}: LiveAnimatedTableProps<T>): JSX.Element {
    const prevPositionsRef = useRef<Map<string, number>>(new Map())
    const deltaVersionRef = useRef(0)

    const positionDeltas = new Map<string, number>()
    items.forEach((item, index) => {
        const key = keyExtractor(item)
        const prevPosition = prevPositionsRef.current.get(key)
        if (prevPosition !== undefined && prevPosition !== index) {
            positionDeltas.set(key, index - prevPosition)
        }
    })

    if (positionDeltas.size > 0) {
        deltaVersionRef.current++
    }

    useLayoutEffect(() => {
        prevPositionsRef.current = new Map(items.map((item, index) => [keyExtractor(item), index]))
    }, [items, keyExtractor])

    return (
        <div className={clsx('bg-bg-light rounded-lg border p-4', className)}>
            <h3 className="text-sm font-semibold mb-4">{title}</h3>
            {isLoading ? (
                <div className="space-y-2">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-8" />
                    ))}
                </div>
            ) : items.length === 0 ? (
                <div className="text-center py-6 text-muted">{emptyMessage}</div>
            ) : (
                <>
                    <div className="flex items-center px-3 py-2 border-b text-xs font-semibold text-muted uppercase">
                        <span className="flex-1">{columnLabel}</span>
                        <span className="w-28 text-center">Views</span>
                    </div>
                    <div className="relative" style={{ height: items.length * ROW_HEIGHT }}>
                        {items.map((item, index) => {
                            const key = keyExtractor(item)
                            const views = viewsExtractor(item)
                            const { node, tooltipTitle } = renderLabel(item)
                            return (
                                <AnimatedRow
                                    key={key}
                                    label={node}
                                    tooltipTitle={tooltipTitle}
                                    views={views}
                                    offset={index * ROW_HEIGHT}
                                    positionDelta={positionDeltas.get(key) ?? 0}
                                    deltaVersion={deltaVersionRef.current}
                                    percentage={totalPageviews > 0 ? (views / totalPageviews) * 100 : 0}
                                />
                            )
                        })}
                    </div>
                </>
            )}
        </div>
    )
}
