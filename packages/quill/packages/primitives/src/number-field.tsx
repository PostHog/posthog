import { NumberField as NumberFieldPrimitive } from '@base-ui/react/number-field'
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from './lib/utils'
import './number-field.css'

function NumberFieldRoot({
    className,
    ...props
}: NumberFieldPrimitive.Root.Props): React.ReactElement {
    return (
        <NumberFieldPrimitive.Root
            data-quill
            data-slot="number-field"
            className={cn('flex flex-col gap-1', className)}
            {...props}
        />
    )
}

function NumberFieldGroup({
    className,
    ...props
}: NumberFieldPrimitive.Group.Props): React.ReactElement {
    return (
        <NumberFieldPrimitive.Group
            data-slot="number-field-group"
            className={cn('quill-number-field__group flex items-center', className)}
            {...props}
        />
    )
}

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

function NumberFieldIncrement({
    className,
    children,
    ...props
}: NumberFieldPrimitive.Increment.Props): React.ReactElement {
    return (
        <NumberFieldPrimitive.Increment
            data-slot="number-field-increment"
            className={cn('quill-number-field__increment flex items-center justify-center', className)}
            {...props}
        >
            {children ?? <ChevronUpIcon className="size-3.5" />}
        </NumberFieldPrimitive.Increment>
    )
}

function NumberFieldDecrement({
    className,
    children,
    ...props
}: NumberFieldPrimitive.Decrement.Props): React.ReactElement {
    return (
        <NumberFieldPrimitive.Decrement
            data-slot="number-field-decrement"
            className={cn('quill-number-field__decrement flex items-center justify-center', className)}
            {...props}
        >
            {children ?? <ChevronDownIcon className="size-3.5" />}
        </NumberFieldPrimitive.Decrement>
    )
}

function NumberFieldScrubArea({
    className,
    ...props
}: NumberFieldPrimitive.ScrubArea.Props): React.ReactElement {
    return (
        <NumberFieldPrimitive.ScrubArea
            data-slot="number-field-scrub-area"
            className={cn('cursor-ew-resize', className)}
            {...props}
        />
    )
}

function NumberFieldScrubAreaCursor({
    className,
    ...props
}: NumberFieldPrimitive.ScrubAreaCursor.Props): React.ReactElement {
    return (
        <NumberFieldPrimitive.ScrubAreaCursor
            data-slot="number-field-scrub-area-cursor"
            className={cn(className)}
            {...props}
        />
    )
}

export {
    NumberFieldRoot,
    NumberFieldGroup,
    NumberFieldInput,
    NumberFieldIncrement,
    NumberFieldDecrement,
    NumberFieldScrubArea,
    NumberFieldScrubAreaCursor,
}
