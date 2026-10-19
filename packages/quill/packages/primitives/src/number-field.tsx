import { NumberField as NumberFieldPrimitive } from '@base-ui/react/number-field'
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from './lib/utils'
import './number-field.css'

const NumberFieldRoot = React.forwardRef<
    React.ComponentRef<typeof NumberFieldPrimitive.Root>,
    NumberFieldPrimitive.Root.Props
>(function NumberFieldRoot({ className, ...props }, ref) {
    return (
        <NumberFieldPrimitive.Root
            ref={ref}
            data-quill
            data-slot="number-field"
            className={cn('flex flex-col gap-1', className)}
            {...props}
        />
    )
})

const NumberFieldGroup = React.forwardRef<
    React.ComponentRef<typeof NumberFieldPrimitive.Group>,
    NumberFieldPrimitive.Group.Props
>(function NumberFieldGroup({ className, ...props }, ref) {
    return (
        <NumberFieldPrimitive.Group
            ref={ref}
            data-slot="number-field-group"
            className={cn('quill-number-field__group flex items-center', className)}
            {...props}
        />
    )
})

const NumberFieldInput = React.forwardRef<HTMLInputElement, NumberFieldPrimitive.Input.Props>(
    ({ className, ...props }, ref) => {
        return (
            <NumberFieldPrimitive.Input
                ref={ref}
                data-slot="number-field-input"
                className={cn('quill-number-field__input', className)}
                {...props}
            />
        )
    }
)
NumberFieldInput.displayName = 'NumberFieldInput'

const NumberFieldIncrement = React.forwardRef<
    React.ComponentRef<typeof NumberFieldPrimitive.Increment>,
    NumberFieldPrimitive.Increment.Props
>(function NumberFieldIncrement({ className, children, ...props }, ref) {
    return (
        <NumberFieldPrimitive.Increment
            ref={ref}
            data-slot="number-field-increment"
            className={cn('quill-number-field__increment flex items-center justify-center', className)}
            {...props}
        >
            {children ?? <ChevronUpIcon className="size-3.5" />}
        </NumberFieldPrimitive.Increment>
    )
})

const NumberFieldDecrement = React.forwardRef<
    React.ComponentRef<typeof NumberFieldPrimitive.Decrement>,
    NumberFieldPrimitive.Decrement.Props
>(function NumberFieldDecrement({ className, children, ...props }, ref) {
    return (
        <NumberFieldPrimitive.Decrement
            ref={ref}
            data-slot="number-field-decrement"
            className={cn('quill-number-field__decrement flex items-center justify-center', className)}
            {...props}
        >
            {children ?? <ChevronDownIcon className="size-3.5" />}
        </NumberFieldPrimitive.Decrement>
    )
})

const NumberFieldScrubArea = React.forwardRef<
    React.ComponentRef<typeof NumberFieldPrimitive.ScrubArea>,
    NumberFieldPrimitive.ScrubArea.Props
>(function NumberFieldScrubArea({ className, ...props }, ref) {
    return (
        <NumberFieldPrimitive.ScrubArea
            ref={ref}
            data-slot="number-field-scrub-area"
            className={cn('cursor-ew-resize', className)}
            {...props}
        />
    )
})

const NumberFieldScrubAreaCursor = React.forwardRef<
    React.ComponentRef<typeof NumberFieldPrimitive.ScrubAreaCursor>,
    NumberFieldPrimitive.ScrubAreaCursor.Props
>(function NumberFieldScrubAreaCursor({ className, ...props }, ref) {
    return (
        <NumberFieldPrimitive.ScrubAreaCursor
            ref={ref}
            data-slot="number-field-scrub-area-cursor"
            className={cn(className)}
            {...props}
        />
    )
})

export {
    NumberFieldRoot,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldIncrement,
    NumberFieldDecrement,
    NumberFieldScrubArea,
    NumberFieldScrubAreaCursor,
}
