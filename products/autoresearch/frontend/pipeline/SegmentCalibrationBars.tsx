import { SegmentCalibration, percent } from '../onlinePerformance'

function Bar({
    label,
    value,
    max,
    className,
}: {
    label: string
    value: number
    max: number
    className: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-2 text-xs">
            <span className="w-16 shrink-0 text-muted">{label}</span>
            <div className="flex-1 min-w-0 h-3 rounded bg-surface-secondary">
                <div className={`h-full rounded ${className}`} style={{ width: `${(100 * value) / max}%` }} />
            </div>
            <span className="w-12 shrink-0 text-right tabular-nums">{percent(value)}</span>
        </div>
    )
}

/** Predicted against actual rate for each likelihood segment on one matured date. */
export function SegmentCalibrationBars({ segments }: { segments: SegmentCalibration[] }): JSX.Element {
    const max = Math.max(...segments.flatMap((s) => [s.predicted, s.actual]), 0.01)
    return (
        <div className="space-y-3 max-w-2xl">
            {segments.map(({ segment, people, predicted, actual }) => (
                <div key={segment.key} className="space-y-1">
                    <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
                        <span className={`inline-block w-2 h-2 rounded-full ${segment.colorClassName}`} />
                        <span className="font-semibold">{segment.label}</span>
                        <span className="text-xs text-muted">
                            {segment.range} · {people.toLocaleString()} people
                        </span>
                    </div>
                    <Bar
                        label="Predicted"
                        value={predicted}
                        max={max}
                        className={`${segment.colorClassName} opacity-50`}
                    />
                    <Bar label="Actual" value={actual} max={max} className={segment.colorClassName} />
                </div>
            ))}
        </div>
    )
}
