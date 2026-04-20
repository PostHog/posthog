import { Slider as SliderPrimitive } from '@base-ui/react/slider'
import * as React from 'react'

import { cn } from './lib/utils'

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
            className={cn('data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full', className)}
            data-slot="slider"
            defaultValue={defaultValue}
            value={value}
            min={min}
            max={max}
            thumbAlignment="edge"
            {...props}
        >
            <SliderPrimitive.Control className="relative flex w-full touch-none items-center select-none data-disabled:opacity-50 data-[orientation=vertical]:h-full data-[orientation=vertical]:min-h-40 data-[orientation=vertical]:w-4 data-[orientation=vertical]:flex-col">
                <SliderPrimitive.Track
                    data-slot="slider-track"
                    className="relative grow overflow-hidden rounded-md bg-input/50 select-none data-[orientation=horizontal]:h-4 data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full data-[orientation=vertical]:w-4"
                >
                    <SliderPrimitive.Indicator
                        data-slot="slider-range"
                        className="bg-primary select-none data-[orientation=horizontal]:h-full data-[orientation=vertical]:w-full"
                    />
                </SliderPrimitive.Track>
                {Array.from({ length: _values.length }, (_, index) => (
                    <SliderPrimitive.Thumb
                        data-slot="slider-thumb"
                        key={index}
                        className="absolute flex items-center justify-center size-4 shrink-0 rounded-full border-2 border-primary bg-background ring-ring/30 transition-colors select-none hover:ring-4 focus-visible:ring-4 focus-visible:outline-hidden disabled:pointer-events-none disabled:opacity-50 before:block before:size-2 before:rounded-full before:bg-background data-[orientation=horizontal]:top-1/2 data-[orientation=horizontal]:-translate-y-1/2 data-[orientation=vertical]:left-1/2 data-[orientation=vertical]:-translate-x-1/2"
                    />
                ))}
            </SliderPrimitive.Control>
        </SliderPrimitive.Root>
    )
}

export { Slider }
