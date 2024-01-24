import clsx from 'clsx'
import { useEventListener } from 'lib/hooks/useEventListener'
import { useRef } from 'react'

export interface LemonSliderProps {
    value?: number
    onChange?: (value: number) => void
    min: number
    max: number
    /** @default 1 */
    step?: number
    className?: string
}

export function LemonSlider({ value = 0, onChange, min, max, step = 1, className }: LemonSliderProps): JSX.Element {
    const trackRef = useRef<HTMLDivElement>(null)
    const movementStartValueWithX = useRef<[number, number] | null>(null)

    useEventListener('mousemove', (e) => {
        if (e.button === 0 && trackRef.current && movementStartValueWithX.current !== null) {
            const [movementStartValue, movementStartX] = movementStartValueWithX.current
            const rect = trackRef.current.getBoundingClientRect()
            const adjustedWidth = rect.width - 16 // 16px = handle width
            const deltaX = (e.clientX - movementStartX) / adjustedWidth
            let newValue = movementStartValue + (max - min) * deltaX
            newValue = Math.max(min, Math.min(max, newValue)) // Clamped
            if (step !== undefined) {
                newValue = Math.round(newValue / step) * step // Adjusted to step
            }
            onChange?.(newValue)
        }
    })
    useEventListener('mouseup', (e) => {
        if (e.button === 0) {
            movementStartValueWithX.current = null
        }
    })

    const proportion = Math.round(((value - min) / (max - min)) * 100) / 100

    // Use only Tailwind
    return (
        <div className={clsx('flex items-center relative my-2.5 min-w-16 select-none', className)}>
            <div
                className="w-full h-3 flex items-center cursor-pointer"
                ref={trackRef}
                onMouseDown={(e) => {
                    const rect = e.currentTarget.getBoundingClientRect()
                    const x = e.clientX - (rect.left + 8) // 4px = half the handle
                    const adjustedWidth = rect.width - 16 // 8px = handle width
                    let newValue = (x / adjustedWidth) * (max - min) + min
                    newValue = Math.max(min, Math.min(max, newValue)) // Clamped
                    if (step !== undefined) {
                        newValue = Math.round(newValue / step) * step // Adjusted to step
                    }
                    onChange?.(newValue)
                }}
            >
                <div className="w-full bg-border rounded-full h-1" />
            </div>
            <div
                className="absolute h-1 bg-primary rounded-full pointer-events-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: `${proportion * 100}%` }}
            />
            <div
                className="absolute size-3 box-content border-2 border-bg-light bg-primary rounded-full cursor-pointer"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    left: `calc(${proportion * 100}% - ${proportion}rem)`,
                }}
                onMouseDown={(e) => {
                    movementStartValueWithX.current = [value, e.clientX]
                }}
            />
        </div>
    )
}
