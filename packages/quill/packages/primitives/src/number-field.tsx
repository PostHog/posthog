import { NumberField as NumberFieldPrimitive } from '@base-ui/react/number-field'
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from './lib/utils'

function NumberFieldRoot({
    className,
    ...props
}: NumberFieldPrimitive.Root.Props): React.ReactElement {
    return (
        <NumberFieldPrimitive.Root
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
            className={cn(
                'flex h-8 items-center rounded-md border border-input bg-input/20 dark:bg-input/30 transition-colors has-[:focus-visible]:border-ring/50 has-[:focus-visible]:ring-3 has-[:focus-visible]:ring-ring/30 has-[:disabled]:opacity-50',
                className
            )}
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
                className={cn(
                    'h-full w-full min-w-0 flex-1 bg-transparent px-2 py-0.5 text-center text-xs tabular-nums outline-none placeholder:text-muted-foreground disabled:pointer-events-none disabled:cursor-not-allowed',
                    className
                )}
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
            className={cn(
                'flex h-full items-center justify-center border-l border-input px-1 text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground disabled:pointer-events-none disabled:opacity-50',
                className
            )}
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
            className={cn(
                'flex h-full items-center justify-center border-r border-input px-1 text-muted-foreground transition-colors hover:bg-fill-hover hover:text-foreground disabled:pointer-events-none disabled:opacity-50',
                className
            )}
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
