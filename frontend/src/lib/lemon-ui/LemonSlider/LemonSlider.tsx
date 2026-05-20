import clsx from 'clsx'
import { useRef, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { useEventListener } from 'lib/hooks/useEventListener'

export interface LemonSliderTick {
    value: number
    label?: string
}

export interface LemonSliderProps {
    value?: number
    onChange?: (value: number) => void
    min: number
    max: number
    /** @default 1 */
    step?: number
    className?: string
    /** Optional tick marks with labels that can be clicked to jump to that value */
    ticks?: LemonSliderTick[]
    /** Reason the slider is disabled - shown in a tooltip. */
    disabledReason?: React.ReactNode | null | false
}

export function LemonSlider({
    value = 0,
    onChange,
    min,
    max,
    step = 1,
    className,
    ticks,
    disabledReason,
}: LemonSliderProps): JSX.Element {
    const isDisabled = !!disabledReason
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
        <Tooltip title={disabledReason ?? undefined}>
            <div className={clsx('select-none', ticks ? 'pb-5' : '', isDisabled && 'opacity-50', className)}>
                <div className="flex items-center relative my-2.5 min-w-16">
                    <div
                        className={clsx(
                            'w-full h-3 flex items-center',
                            isDisabled ? 'cursor-not-allowed' : 'cursor-pointer'
                        )}
                        ref={trackRef}
                        onMouseDown={
                            isDisabled
                                ? undefined
                                : (e) => {
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
                                  }
                        }
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
                            'absolute size-3 box-content border-2 border-primary rounded-full bg-accent transition-shadow duration-75',
                            isDisabled ? 'cursor-not-allowed' : 'cursor-pointer',
                            dragging ? 'ring-2 scale-90' : isDisabled ? 'ring-0' : 'ring-0 hover:ring-2 focus:ring-2'
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
                        aria-disabled={isDisabled}
                        tabIndex={isDisabled ? -1 : 0}
                        onKeyDown={isDisabled ? undefined : handleKeyDown}
                        onMouseDown={
                            isDisabled
                                ? undefined
                                : (e) => {
                                      movementStartValueWithX.current = [constrainedValue, e.clientX]
                                      setDragging(true)
                                  }
                        }
                        onTouchStart={
                            isDisabled
                                ? undefined
                                : (e) => {
                                      movementStartValueWithX.current = [constrainedValue, e.touches[0].clientX]
                                      setDragging(true)
                                  }
                        }
                    />
                    {/* Tick marks */}
                    {ticks && (
                        <div className="absolute top-full left-0 right-0 mt-1">
                            {ticks.map((tick) => {
                                const tickProportion = (tick.value - min) / (max - min)
                                return (
                                    <button
                                        key={tick.value}
                                        type="button"
                                        className={clsx(
                                            'absolute text-xs transition-all px-1 py-0.5 -translate-x-1/2 rounded',
                                            isDisabled ? 'cursor-not-allowed' : 'cursor-pointer',
                                            constrainedValue === tick.value
                                                ? 'text-primary-3000 font-semibold bg-primary-highlight'
                                                : 'text-muted hover:text-primary hover:bg-primary-highlight'
                                        )}
                                        // eslint-disable-next-line react/forbid-dom-props
                                        style={{
                                            left: `calc(${tickProportion * 100}% - ${tickProportion - 0.5}rem)`,
                                        }}
                                        onClick={isDisabled ? undefined : () => onChange?.(tick.value)}
                                    >
                                        {tick.label ?? tick.value}
                                    </button>
                                )
                            })}
                        </div>
                    )}
                </div>
            </div>
        </Tooltip>
    )
}
