import { cn } from '@posthog/quill'

// A day with any count stays visibly taller than an empty day, and the partial last day stays readable.
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

export function TodayInlineTrend({
    values,
    type,
    detailed = false,
    partialLast = false,
}: {
    values: number[]
    type: 'bar' | 'line'
    /** In a card, empty days show as a baseline. */
    detailed?: boolean
    /** The last value covers only part of its period, so it is drawn as an outline. */
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
            {values.map((value, index) =>
                partialLast && index === values.length - 1 ? (
                    <span
                        key={index}
                        className={cn(
                            'flex-1 rounded-t-[1px]',
                            detailed
                                ? 'border border-b-0 border-dashed border-current bg-current/15 opacity-60'
                                : 'bg-current opacity-25'
                        )}
                        style={{ height: `${Math.max(MIN_PARTIAL_PERCENT, (value / max) * 100)}%` }}
                    />
                ) : detailed && value === max && value > 0 ? (
                    <span
                        key={index}
                        className="relative flex-1 rounded-t-[1px] bg-[var(--today-marker)]"
                        style={{ height: `${Math.max(MIN_BAR_PERCENT, (value / max) * 100)}%` }}
                    >
                        <span className="absolute -top-4 left-1/2 -translate-x-1/2 text-xxs font-semibold text-[var(--foreground)] tabular-nums">
                            {value.toLocaleString('en-US')}
                        </span>
                    </span>
                ) : (
                    <span
                        key={index}
                        className={cn(
                            'flex-1 rounded-t-[1px]',
                            value > 0 ? 'bg-current opacity-60' : detailed && 'h-px bg-current opacity-30',
                            value === max && value > 0 && 'bg-[var(--today-marker)] opacity-100'
                        )}
                        style={value > 0 ? { height: `${Math.max(MIN_BAR_PERCENT, (value / max) * 100)}%` } : undefined}
                    />
                )
            )}
        </span>
    )
}
