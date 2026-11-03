import './TodayDotRingSpinner.scss'

import { cn } from '@posthog/quill'

const RING_DOTS = [
    'row-start-1 col-start-2 [animation-delay:0ms]',
    'row-start-1 col-start-3 [animation-delay:112.5ms]',
    'row-start-2 col-start-3 [animation-delay:225ms]',
    'row-start-3 col-start-3 [animation-delay:337.5ms]',
    'row-start-3 col-start-2 [animation-delay:450ms]',
    'row-start-3 col-start-1 [animation-delay:562.5ms]',
    'row-start-2 col-start-1 [animation-delay:675ms]',
    'row-start-1 col-start-1 [animation-delay:787.5ms]',
]

export function TodayDotRingSpinner({ className }: { className?: string }): JSX.Element {
    return (
        <span aria-hidden className={cn('grid size-2.5 shrink-0 grid-cols-3 grid-rows-3', className)}>
            {RING_DOTS.map((position) => (
                <span
                    key={position}
                    className={cn(
                        'TodayDotRingSpinner__dot size-0.5 place-self-center rounded-full bg-current',
                        position
                    )}
                />
            ))}
        </span>
    )
}
