import { useEffect, useRef } from 'react'

const RING_RADIUS = 7
const RING_LENGTH = 2 * Math.PI * RING_RADIUS

/**
 * A ring that fills over `durationMs`, then calls `onDone`. Mount it with a new `key` to restart it.
 * The ring is drawn through a ref on each frame, so the countdown does not re-render the card around it.
 */
export function TodayTourTimer({
    durationMs,
    paused,
    onDone,
}: {
    durationMs: number
    paused: boolean
    onDone: () => void
}): JSX.Element {
    const ringRef = useRef<SVGCircleElement>(null)
    const elapsedRef = useRef(0)
    const onDoneRef = useRef(onDone)
    onDoneRef.current = onDone

    useEffect(() => {
        if (paused) {
            return
        }
        let frame = 0
        let last = performance.now()
        const tick = (now: number): void => {
            elapsedRef.current = Math.min(durationMs, elapsedRef.current + now - last)
            last = now
            ringRef.current?.setAttribute(
                'stroke-dashoffset',
                String(RING_LENGTH * (1 - elapsedRef.current / durationMs))
            )
            if (elapsedRef.current >= durationMs) {
                onDoneRef.current()
                return
            }
            frame = requestAnimationFrame(tick)
        }
        frame = requestAnimationFrame(tick)
        return () => cancelAnimationFrame(frame)
    }, [paused, durationMs])

    return (
        <svg viewBox="0 0 18 18" className="size-4.5 shrink-0 -rotate-90 text-muted-foreground" aria-hidden="true">
            <circle
                cx="9"
                cy="9"
                r={RING_RADIUS}
                fill="none"
                stroke="currentColor"
                strokeOpacity={0.25}
                strokeWidth="2"
            />
            <circle
                ref={ringRef}
                cx="9"
                cy="9"
                r={RING_RADIUS}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeDasharray={RING_LENGTH}
                strokeDashoffset={RING_LENGTH}
            />
        </svg>
    )
}
