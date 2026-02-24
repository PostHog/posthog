import clsx from 'clsx'
import { useMemo } from 'react'

import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColorPalette } from 'lib/colors'

interface BreakdownItem {
    count: number
    percentage: number
}

interface BreakdownLiveCardProps<T extends BreakdownItem> {
    title: string
    data: T[]
    getKey: (item: T) => string
    getLabel: (item: T) => string
    renderIcon?: (item: T) => JSX.Element
    emptyMessage: string
    statLabel: string
    totalCount?: number
    isLoading?: boolean
}

export const BreakdownLiveCard = <T extends BreakdownItem>({
    title,
    data,
    getKey,
    getLabel,
    renderIcon,
    emptyMessage,
    statLabel,
    totalCount,
    isLoading,
}: BreakdownLiveCardProps<T>): JSX.Element => {
    const colors = useMemo(() => getSeriesColorPalette(), [])

    const processedData = useMemo(() => {
        if (data.length === 0) {
            return []
        }

        // Sort by percentage, but always keep "Other" at the end
        return [...data]
            .sort((a, b) => {
                const aLabel = getLabel(a).toLowerCase()
                const bLabel = getLabel(b).toLowerCase()
                if (aLabel === 'other') {
                    return 1
                }
                if (bLabel === 'other') {
                    return -1
                }
                return b.percentage - a.percentage
            })
            .map((d, index) => ({ item: d, color: colors[index % colors.length] }))
    }, [data, colors, getLabel])

    const computedTotalCount = useMemo(() => {
        if (totalCount !== undefined) {
            return totalCount
        }
        return data.reduce((sum, d) => sum + d.count, 0)
    }, [data, totalCount])

    const hasData = data.length > 0 && data.some((d) => d.count > 0)

    return (
        <div className="bg-bg-light rounded-lg border border-border p-4 h-full flex flex-col">
            <div className="mb-4">
                <h3 className="text-sm font-semibold text-default">{title}</h3>
            </div>

            {isLoading ? (
                <div className="flex-1 flex items-center justify-center">
                    <Spinner className="text-2xl" />
                </div>
            ) : !hasData ? (
                <div className="flex-1 flex items-center justify-center text-muted text-sm">{emptyMessage}</div>
            ) : (
                <>
                    <div className="text-center mb-4">
                        <div className="text-3xl font-bold tabular-nums">{computedTotalCount.toLocaleString()}</div>
                        <div className="text-xs text-muted">{statLabel}</div>
                    </div>

                    <div className="space-y-2">
                        {processedData.map(({ item, color }, index) => {
                            const isTop = index === 0
                            const key = getKey(item)
                            const label = getLabel(item)

                            return (
                                <Tooltip key={key} title={`${item.count.toLocaleString()} ${statLabel} · ${label}`}>
                                    <div className="flex items-center gap-2 cursor-default">
                                        {renderIcon && renderIcon(item)}
                                        <div
                                            className={clsx(
                                                'text-xs truncate',
                                                renderIcon ? 'w-14' : 'w-16',
                                                isTop ? 'text-default font-medium' : 'text-muted'
                                            )}
                                        >
                                            {label}
                                        </div>
                                        <div className="flex-1 h-2 bg-border-light rounded-full overflow-hidden">
                                            <div
                                                className="h-full rounded-full transition-all duration-300 ease-out"
                                                style={{
                                                    width: `${item.percentage}%`,
                                                    backgroundColor: color,
                                                }}
                                            />
                                        </div>
                                        <div
                                            className={clsx(
                                                'w-10 text-xs text-right tabular-nums',
                                                isTop ? 'text-default font-medium' : 'text-muted'
                                            )}
                                        >
                                            {item.percentage.toFixed(0)}%
                                        </div>
                                    </div>
                                </Tooltip>
                            )
                        })}
                    </div>
                </>
            )}
        </div>
    )
}
