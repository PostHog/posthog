import { cn } from 'lib/utils/css-classes'

import { formatLatencyMs } from './formatStats'

const TICKS = [
    { fraction: 0, className: 'left-0' },
    { fraction: 0.25, className: 'left-1/4' },
    { fraction: 0.5, className: 'left-1/2' },
    { fraction: 0.75, className: 'left-3/4' },
]

export interface TimelineAxisProps {
    totalMs: number
}

export function TimelineAxis({ totalMs }: TimelineAxisProps): JSX.Element {
    return (
        <div className="relative h-5 font-mono text-xs text-secondary">
            {TICKS.map((tick) => (
                <span key={tick.fraction} className={cn('absolute top-0.5', tick.className)}>
                    {formatLatencyMs(totalMs * tick.fraction)}
                </span>
            ))}
        </div>
    )
}
