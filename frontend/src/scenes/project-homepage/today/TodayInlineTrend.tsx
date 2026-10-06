import { cn } from '@posthog/quill'

const MIN_BAR_PERCENT = 22
const MIN_PARTIAL_PERCENT = 30
const WIDTH = 56
const HEIGHT = 14

function linePoints(values: number[]): string {
    const min = Math.min(...values)
    const range = Math.max(...values) - min
    const step = WIDTH / Math.max(values.length - 1, 1)
    return values
        .map(
            (value, index) => `${index * step},${range === 0 ? HEIGHT / 2 : HEIGHT - ((value - min) / range) * HEIGHT}`
        )
        .join(' ')
}

function barHeight(value: number, max: number, minPercent: number): { height: string } {
    return { height: `${Math.max(minPercent, (value / max) * 100)}%` }
}

function TrendBar({
    value,
    max,
    partial,
    detailed,
}: {
    value: number
    max: number
    partial: boolean
    detailed: boolean
}): JSX.Element {
    const peak = value === max && value > 0
    if (partial) {
        return (
            <span
                className={cn(
                    'flex-1 rounded-t-[1px]',
                    detailed
                        ? 'border border-b-0 border-dashed border-current bg-current/15 opacity-60'
                        : 'bg-current opacity-25'
                )}
                style={barHeight(value, max, MIN_PARTIAL_PERCENT)}
            />
        )
    }
    if (detailed && peak) {
        return (
            <span
                className="relative flex-1 rounded-t-[1px] bg-[var(--today-marker)]"
                style={barHeight(value, max, MIN_BAR_PERCENT)}
            >
                <span className="absolute -top-4 left-1/2 -translate-x-1/2 text-xxs font-semibold text-foreground tabular-nums">
                    {value.toLocaleString('en-US')}
                </span>
            </span>
        )
    }
    if (value <= 0) {
        return <span className={cn('flex-1 rounded-t-[1px]', detailed && 'h-px bg-current opacity-30')} />
    }
    return (
        <span
            className={cn(
                'flex-1 rounded-t-[1px] bg-current opacity-60',
                peak && 'bg-[var(--today-marker)] opacity-100'
            )}
            style={barHeight(value, max, MIN_BAR_PERCENT)}
        />
    )
}

export function TodayInlineTrend({
    values,
    type,
    detailed = false,
    partialLast = false,
}: {
    values: number[]
    type: 'bar' | 'line'
    detailed?: boolean
    partialLast?: boolean
}): JSX.Element {
    if (type === 'line') {
        return (
            <svg
                className="h-4 w-16 overflow-visible text-muted-foreground opacity-60"
                viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
                preserveAspectRatio="none"
                aria-hidden
            >
                <polyline
                    points={linePoints(values)}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.5}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    vectorEffect="non-scaling-stroke"
                />
            </svg>
        )
    }
    const max = Math.max(...values, 1)
    return (
        <span className="inline-flex h-4 w-16 items-end gap-px text-muted-foreground" aria-hidden>
            {values.map((value, index) => (
                <TrendBar
                    key={index}
                    value={value}
                    max={max}
                    partial={partialLast && index === values.length - 1}
                    detailed={detailed}
                />
            ))}
        </span>
    )
}
