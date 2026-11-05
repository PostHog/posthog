import { Radio as RadioPrimitive } from '@base-ui/react/radio'
import { RadioGroup as RadioGroupPrimitive } from '@base-ui/react/radio-group'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import './radio-group.css'
import { cn } from './lib/utils'

const radioIndicatorVariants = cva('quill-radio-indicator', {
    variants: {
        size: {
            default: 'quill-radio-indicator--size-default',
            sm: 'quill-radio-indicator--size-sm',
        },
    },
    defaultVariants: {
        size: 'default',
    },
})

const radioDotVariants = cva('quill-radio-dot', {
    variants: {
        size: {
            default: 'quill-radio-dot--size-default',
            sm: 'quill-radio-dot--size-sm',
        },
    },
    defaultVariants: {
        size: 'default',
    },
})

const RadioIndicator = React.forwardRef<
    HTMLSpanElement,
    { checked?: boolean; className?: string } & VariantProps<typeof radioIndicatorVariants>
>(function RadioIndicator({ checked, className, size = 'default' }, ref) {
    return (
        <span
            ref={ref}
            data-slot="radio-indicator"
            className={cn(radioIndicatorVariants({ size }), checked && 'quill-radio-indicator--checked', className)}
        >
            {checked && <span className={radioDotVariants({ size })} />}
        </span>
    )
})

const RadioGroup = React.forwardRef<React.ComponentRef<typeof RadioGroupPrimitive>, RadioGroupPrimitive.Props>(
    function RadioGroup({ className, ...props }, ref) {
        return (
            <RadioGroupPrimitive
                ref={ref}
                data-quill
                data-slot="radio-group"
                className={cn('grid w-full gap-3', className)}
                {...props}
            />
        )
    }
)

const radioGroupItemVariants = cva('quill-radio group/radio-group-item peer', {
    variants: {
        size: {
            default: 'quill-radio--size-default',
            sm: 'quill-radio--size-sm',
        },
    },
    defaultVariants: {
        size: 'default',
    },
})

const radioGroupItemIndicatorVariants = cva('quill-radio__indicator', {
    variants: {
        size: {
            default: 'quill-radio__indicator--size-default',
            sm: 'quill-radio__indicator--size-sm',
        },
    },
    defaultVariants: {
        size: 'default',
    },
})

const RadioGroupItem = React.forwardRef<
    React.ComponentRef<typeof RadioPrimitive.Root>,
    RadioPrimitive.Root.Props & VariantProps<typeof radioGroupItemVariants>
>(function RadioGroupItem({ className, size = 'default', ...props }, ref) {
    return (
        <RadioPrimitive.Root
            ref={ref}
            data-slot="radio-group-item"
            className={cn(radioGroupItemVariants({ size }), className)}
            {...props}
        >
            <RadioPrimitive.Indicator
                data-slot="radio-group-indicator"
                className={radioGroupItemIndicatorVariants({ size })}
            >
                <span className={radioDotVariants({ size })} />
            </RadioPrimitive.Indicator>
        </RadioPrimitive.Root>
    )
})

export { RadioGroup, RadioGroupItem, RadioIndicator }
