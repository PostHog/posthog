import clsx from 'clsx'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils/numbers'

const formatCount = (count: number, total: number): string => {
    if ((count / total) * 100 < 3) {
        return ''
    }
    return `${humanFriendlyNumber(count)}`
}

// Define a type for the color classes to ensure type safety
type ColorClass = 'bg-brand-blue' | 'bg-warning' | 'bg-success' | 'bg-danger' | 'bg-muted'

export interface StackedBarSegment {
    count: number
    label: string
    colorClass: ColorClass
    tooltip?: string
}

type StackedBarSize = 'md' | 'sm'

const SIZE_CONFIG: Record<StackedBarSize, { bar: string; label: string; legend: string }> = {
    md: { bar: 'h-10', label: 'leading-10 text-base', legend: 'text-secondary' },
    sm: { bar: 'h-2', label: '', legend: 'text-sm' },
}

export function StackedBarSkeleton({
    className,
    size = 'md',
}: {
    className?: string
    size?: StackedBarSize
}): JSX.Element {
    const sizeClasses = SIZE_CONFIG[size]
    return (
        <div className={clsx('@container/stacked-bar flex flex-col gap-2', className)}>
            <div className={clsx('relative w-full flex mx-auto', sizeClasses.bar)}>
                <LemonSkeleton className={clsx('w-1/4 rounded-r-none opacity-60', sizeClasses.bar)} />
                <LemonSkeleton className={clsx('w-1/2 rounded-none opacity-80', sizeClasses.bar)} />
                <LemonSkeleton className={clsx('w-1/4 rounded-l-none opacity-100', sizeClasses.bar)} />
            </div>
            <div
                className={clsx(
                    size === 'sm'
                        ? 'grid grid-cols-1 @min-[48rem]/stacked-bar:grid-cols-3 gap-x-4 gap-y-2'
                        : 'flex flex-wrap items-center gap-4 justify-center'
                )}
            >
                {Array.from({ length: 3 }).map((_, index) => (
                    <div key={index} className="flex items-center gap-2 min-w-0">
                        <LemonSkeleton className="size-3 rounded-full" />
                        <LemonSkeleton className="h-4 w-20" />
                    </div>
                ))}
            </div>
        </div>
    )
}

export function StackedBar({
    segments,
    className,
    size = 'md',
    showTooltips = true,
    barValueFormatter = formatCount,
}: {
    segments: StackedBarSegment[]
    className?: string
    size?: StackedBarSize
    showTooltips?: boolean
    barValueFormatter?: (count: number, total: number) => string
}): JSX.Element | null {
    const sizeClasses = SIZE_CONFIG[size]
    const total = segments.reduce((sum, segment) => sum + segment.count, 0)
    let accumulatedPercentage = 0

    if (total === 0) {
        return null
    }

    return (
        <div className={clsx('@container/stacked-bar flex flex-col gap-2', className)}>
            <div className={clsx('relative w-full mx-auto', sizeClasses.bar)}>
                {segments.map(({ count, label, colorClass, tooltip }, index) => {
                    const percentage = (count / total) * 100
                    const left = accumulatedPercentage
                    accumulatedPercentage += percentage

                    const isFirst = index === 0
                    const isLast = index === segments.length - 1
                    const isOnly = segments.length === 1

                    const segmentContent = (
                        <div
                            key={`stacked-bar-${label}`}
                            className={clsx(
                                'text-white text-center absolute',
                                sizeClasses.bar,
                                colorClass,
                                isFirst || isOnly ? 'rounded-l' : '',
                                isLast || isOnly ? 'rounded-r' : ''
                            )}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                width: `${percentage}%`,
                                left: `${left}%`,
                            }}
                        >
                            {size !== 'sm' && (
                                <span
                                    className={clsx(
                                        'inline-flex font-semibold max-w-full px-1 truncate',
                                        sizeClasses.label
                                    )}
                                >
                                    {barValueFormatter(count, total)}
                                </span>
                            )}
                        </div>
                    )

                    return showTooltips ? (
                        <Tooltip
                            key={`stacked-bar-tooltip-${label}`}
                            title={tooltip || `${label}: ${count} (${percentage.toFixed(1)}%)`}
                            delayMs={0}
                            placement="top"
                        >
                            {segmentContent}
                        </Tooltip>
                    ) : (
                        segmentContent
                    )
                })}
            </div>
            <div className="w-full">
                <div
                    className={clsx(
                        size === 'sm'
                            ? 'grid grid-cols-1 @min-[48rem]/stacked-bar:grid-cols-3 gap-x-4 gap-y-2'
                            : 'flex flex-wrap justify-center gap-x-8 gap-y-2'
                    )}
                >
                    {segments.map(
                        ({ count, label, colorClass }) =>
                            (size === 'sm' || count > 0) && (
                                <div key={`stacked-bar-legend-${label}`} className="flex items-center gap-2 min-w-0">
                                    <div
                                        className={clsx(
                                            'shrink-0 rounded-full',
                                            size === 'sm' ? 'size-2' : 'size-3',
                                            colorClass
                                        )}
                                    />
                                    {size === 'sm' ? (
                                        <div className="flex flex-1 flex-wrap items-baseline justify-between gap-x-2">
                                            <span className="text-secondary">{label}</span>
                                            <span className="tabular-nums whitespace-nowrap">
                                                <span className="font-semibold">{humanFriendlyNumber(count)}</span>{' '}
                                                <span className="text-secondary ml-2">
                                                    {((count / total) * 100).toFixed(1)}%
                                                </span>
                                            </span>
                                        </div>
                                    ) : (
                                        <span className={clsx('font-semibold', sizeClasses.legend)}>{`${label} (${(
                                            (count / total) *
                                            100
                                        ).toFixed(1)}%)`}</span>
                                    )}
                                </div>
                            )
                    )}
                </div>
            </div>
        </div>
    )
}
