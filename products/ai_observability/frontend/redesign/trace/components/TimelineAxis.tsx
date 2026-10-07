import { formatLatencyMs } from './formatStats'
import { TimelineTick } from './timelineTicks'

export interface TimelineAxisProps {
    ticks: TimelineTick[]
    totalMs: number
}

export function TimelineAxis({ ticks, totalMs }: TimelineAxisProps): JSX.Element {
    return (
        <div className="relative h-5 font-mono text-xs text-secondary">
            {ticks.map((tick) => (
                <span
                    key={tick.valueMs}
                    className="absolute top-0.5 pl-0.5"
                    // Tick positions come from the trace duration, so they cannot be static Tailwind classes.
                    style={{ left: `${tick.fraction * 100}%` }}
                >
                    {formatLatencyMs(tick.valueMs)}
                </span>
            ))}
            <span className="absolute top-0.5 right-0 pr-1 font-semibold">{formatLatencyMs(totalMs)}</span>
        </div>
    )
}
