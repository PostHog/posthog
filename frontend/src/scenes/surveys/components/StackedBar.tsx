import clsx from 'clsx'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyNumber } from 'lib/utils'

const formatCount = (count: number, total: number): string => {
    if ((count / total) * 100 < 3) {
        return ''
    }
    return `${humanFriendlyNumber(count)}`
}

// Define a type for the color classes to ensure type safety
type ColorClass = 'bg-brand-blue' | 'bg-warning' | 'bg-success' | 'bg-danger'

export interface StackedBarSegment {
    count: number
    label: string
    colorClass: ColorClass
    tooltip?: string
}

export function StackedBarSkeleton({ className }: { className?: string }): JSX.Element {
    return (
        <div className={clsx('flex flex-col gap-2', className)}>
            <div className="relative w-full flex mx-auto h-10">
                <LemonSkeleton className="w-1/4 h-10 rounded-r-none opacity-60" />
                <LemonSkeleton className="w-1/2 h-10 rounded-none opacity-80" />
                <LemonSkeleton className="w-1/4 h-10 rounded-l-none opacity-100" />
            </div>
            <div className="flex items-center gap-4 justify-center">
                {Array.from({ length: 3 }).map((_, index) => (
                    <div key={index} className="flex items-center gap-2">
                        <LemonSkeleton className="size-3 rounded-full" />
                        <LemonSkeleton className="h-6 w-24" />
                    </div>
                ))}
            </div>
        </div>
    )
}

export function StackedBar({
    segments,
    className,
}: {
    segments: StackedBarSegment[]
    className?: string
}): JSX.Element | null {
    const total = segments.reduce((sum, segment) => sum + segment.count, 0)
    let accumulatedPercentage = 0

    if (total === 0) {
        return null
    }

    return (
        <div className={clsx('flex flex-col gap-2', className)}>
            <div className="relative w-full mx-auto h-10">
                {segments.map(({ count, label, colorClass, tooltip }, index) => {
                    const percentage = (count / total) * 100
                    const left = accumulatedPercentage
                    accumulatedPercentage += percentage

                    const isFirst = index === 0
                    const isLast = index === segments.length - 1
                    const isOnly = segments.length === 1

                    return (
                        <Tooltip
                            key={`stacked-bar-${label}`}
                            title={tooltip || `${label}: ${count} (${percentage.toFixed(1)}%)`}
                            delayMs={0}
                            placement="top"
                        >
                            <div
                                className={clsx(
                                    'h-10 text-white text-center absolute cursor-pointer',
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
                                <span className="inline-flex font-semibold max-w-full px-1 truncate leading-10">
                                    {formatCount(count, total)}
                                </span>
                            </div>
                        </Tooltip>
                    )
                })}
            </div>
            <div className="w-full flex justify-center">
                <div className="flex items-center gap-8">
                    {segments.map(
                        ({ count, label, colorClass }) =>
                            count > 0 && (
                                <div key={`stacked-bar-legend-${label}`} className="flex items-center gap-2">
                                    <div className={clsx('size-3 rounded-full', colorClass)} />
                                    <span className="font-semibold text-secondary">{`${label} (${(
                                        (count / total) *
                                        100
                                    ).toFixed(1)}%)`}</span>
                                </div>
                            )
                    )}
                </div>
            </div>
        </div>
    )
}
