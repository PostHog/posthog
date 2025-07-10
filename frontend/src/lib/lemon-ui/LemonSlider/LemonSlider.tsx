import clsx from 'clsx'
import { useRef, useState } from 'react'

import { useEventListener } from 'lib/hooks/useEventListener'

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
    const [dragging, setDragging] = useState(false)

    const handleMove = (clientX: number): void => {
        if (trackRef.current && movementStartValueWithX.current !== null) {
            const [movementStartValue, movementStartX] = movementStartValueWithX.current
            const rect = trackRef.current.getBoundingClientRect()
            const adjustedWidth = rect.width - 16 // 16px = handle width
            const deltaX = (clientX - movementStartX) / adjustedWidth
            let newValue = movementStartValue + (max - min) * deltaX
            newValue = Math.max(min, Math.min(max, newValue)) // Clamped
            if (step !== undefined) {
                newValue = Math.round(newValue / step) * step // Adjusted to step
            }
            onChange?.(newValue)
        }
    }
    useEventListener('mousemove', (e) => {
        handleMove(e.clientX)
    })
    useEventListener('touchmove', (e) => {
        if (e.touches.length === 1) {
            handleMove(e.touches[0].clientX)
        }
    })

    useEventListener('mouseup', (e) => {
        if (e.button === 0) {
            movementStartValueWithX.current = null
            setDragging(false)
        }
    })
    useEventListener('touchend', () => {
        movementStartValueWithX.current = null
        setDragging(false)
    })
    useEventListener('touchcancel', () => {
        movementStartValueWithX.current = null
        setDragging(false)
    })

    const handleKeyDown = (e: React.KeyboardEvent): void => {
        const stepSize = e.shiftKey ? step * 10 : step // Increased step size with Shift key
        let newValue = constrainedValue

        switch (e.key) {
            case 'ArrowRight':
            case 'ArrowUp':
                newValue = Math.min(max, constrainedValue + stepSize)
                e.preventDefault()
                break
            case 'Home':
                newValue = min
                e.preventDefault()
                break
            case 'End':
                newValue = max
                e.preventDefault()
                break
            case 'PageUp':
                newValue = Math.min(max, constrainedValue + stepSize * 10)
                e.preventDefault()
                break
            case 'PageDown':
                newValue = Math.max(min, constrainedValue - stepSize * 10)
                e.preventDefault()
                break
            case 'ArrowLeft':
            case 'ArrowDown':
                newValue = Math.max(min, constrainedValue - stepSize)
                e.preventDefault()
                break
        }

        if (newValue !== constrainedValue) {
            onChange?.(newValue)
        }
    }

    const constrainedValue = Math.max(min, Math.min(value, max))
    const proportion = isNaN(value) ? 0 : Math.round(((constrainedValue - min) / (max - min)) * 100) / 100

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
                    movementStartValueWithX.current = [newValue, e.clientX]
                    setDragging(true)
                }}
            >
                <div className="w-full bg-fill-slider-rail rounded-full h-[6px]" />
            </div>
            <div
                className="absolute h-[6px] bg-accent rounded-full pointer-events-none"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: `${proportion * 100}%` }}
            />
            <button
                className={clsx(
                    'absolute size-3 box-content border-2 border-primary rounded-full cursor-pointer bg-accent transition-shadow duration-75',
                    dragging ? 'ring-2 scale-90' : 'ring-0 hover:ring-2 focus:ring-2'
                )}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    left: `calc(${proportion * 100}% - ${proportion}rem)`,
                }}
                role="slider"
                type="button"
                aria-valuemin={min}
                aria-valuemax={max}
                aria-valuenow={constrainedValue}
                aria-label={`Slider value: ${constrainedValue}`}
                aria-valuetext={`${constrainedValue}`}
                tabIndex={0}
                onKeyDown={handleKeyDown}
                onMouseDown={(e) => {
                    movementStartValueWithX.current = [constrainedValue, e.clientX]
                    setDragging(true)
                }}
                onTouchStart={(e) => {
                    movementStartValueWithX.current = [constrainedValue, e.touches[0].clientX]
                    setDragging(true)
                }}
            />
        </div>
    )
}
