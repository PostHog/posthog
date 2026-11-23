import './slider.css'

import { Slider as SliderPrimitive } from '@base-ui/react/slider'
import * as React from 'react'

import { cn } from './lib/utils'
import { hasTooltipContent, withDisabledReason } from './with-tooltip'

const Slider = React.forwardRef<
    React.ComponentRef<typeof SliderPrimitive.Root>,
    SliderPrimitive.Root.Props & {
        /** Disables the slider and says why in a tooltip. The slider stays focusable, so the reason is reachable. */
        disabledReason?: React.ReactNode
    }
>(function Slider({ className, defaultValue, value, min = 0, max = 100, disabled, disabledReason, ...props }, ref) {
    const _values = React.useMemo(
        () => (Array.isArray(value) ? value : Array.isArray(defaultValue) ? defaultValue : [min, max]),
        [value, defaultValue, min, max]
    )

    const hasDisabledReason = hasTooltipContent(disabledReason)

    // The root stays hoverable while its thumbs ignore the pointer, so it is the trigger.
    return withDisabledReason(
        <SliderPrimitive.Root
            ref={ref}
            data-quill
            data-slot="slider"
            className={cn('quill-slider', className)}
            defaultValue={defaultValue}
            value={value}
            min={min}
            max={max}
            disabled={disabled || hasDisabledReason}
            thumbAlignment="edge"
            {...props}
        >
            <SliderPrimitive.Control className="quill-slider__control">
                <SliderPrimitive.Track data-slot="slider-track" className="quill-slider__track">
                    <SliderPrimitive.Indicator data-slot="slider-range" className="quill-slider__range" />
                </SliderPrimitive.Track>
                {Array.from({ length: _values.length }, (_, index) => (
                    <SliderPrimitive.Thumb
                        data-slot="slider-thumb"
                        key={index}
                        className="quill-slider__thumb flex items-center justify-center"
                    />
                ))}
            </SliderPrimitive.Control>
        </SliderPrimitive.Root>,
        disabledReason,
        { target: 'self', focusable: true }
    )
})

export { Slider }
