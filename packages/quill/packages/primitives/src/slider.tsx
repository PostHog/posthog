import { Slider as SliderPrimitive } from '@base-ui/react/slider'
import * as React from 'react'

import { cn } from './lib/utils'
import './slider.css'

function Slider({
    className,
    defaultValue,
    value,
    min = 0,
    max = 100,
    ...props
}: SliderPrimitive.Root.Props): React.ReactElement {
    const _values = React.useMemo(
        () => (Array.isArray(value) ? value : Array.isArray(defaultValue) ? defaultValue : [min, max]),
        [value, defaultValue, min, max]
    )

    return (
        <SliderPrimitive.Root
            data-quill
            data-slot="slider"
            className={cn('quill-slider', className)}
            defaultValue={defaultValue}
            value={value}
            min={min}
            max={max}
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
        </SliderPrimitive.Root>
    )
}

export { Slider }
