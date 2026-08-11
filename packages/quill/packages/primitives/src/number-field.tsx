import { NumberField as NumberFieldPrimitive } from '@base-ui/react/number-field'
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from './lib/utils'
import './number-field.css'

/**
 * Groups all parts of the number field and manages its state.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Number Field](https://base-ui.com/react/components/number-field)
 *
 * @baseui NumberField.Root
 */
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

/**
 * Groups the input with the increment and decrement buttons.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Number Field](https://base-ui.com/react/components/number-field)
 *
 * @baseui NumberField.Group
 */
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

/**
 * The native input control in the number field.
 * Renders an `<input>` element.
 *
 * Documentation: [Base UI Number Field](https://base-ui.com/react/components/number-field)
 *
 * @baseui NumberField.Input
 */
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

/**
 * A stepper button that increases the field value when clicked.
 * Renders a `<button>` element.
 *
 * Documentation: [Base UI Number Field](https://base-ui.com/react/components/number-field)
 *
 * @baseui NumberField.Increment
 */
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

/**
 * A stepper button that decreases the field value when clicked.
 * Renders a `<button>` element.
 *
 * Documentation: [Base UI Number Field](https://base-ui.com/react/components/number-field)
 *
 * @baseui NumberField.Decrement
 */
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

/**
 * An interactive area where the user can click and drag to change the field value.
 * Renders a `<span>` element.
 *
 * Documentation: [Base UI Number Field](https://base-ui.com/react/components/number-field)
 *
 * @baseui NumberField.ScrubArea
 */
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

/**
 * A custom element to display instead of the native cursor while using the scrub area.
 * Renders a `<span>` element.
 *
 * This component uses the [Pointer Lock API](https://developer.mozilla.org/en-US/docs/Web/API/Pointer_Lock_API), which may prompt the browser to display a related notification. It is disabled
 * in Safari to avoid a layout shift that this notification causes there.
 *
 * Documentation: [Base UI Number Field](https://base-ui.com/react/components/number-field)
 *
 * @baseui NumberField.ScrubAreaCursor
 */
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
