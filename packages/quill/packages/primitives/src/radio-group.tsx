import './radio-group.css'

import { Radio as RadioPrimitive } from '@base-ui/react/radio'
import { RadioGroup as RadioGroupPrimitive } from '@base-ui/react/radio-group'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { useDisabledControl } from './disabled-reason'
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
    Omit<RadioPrimitive.Root.Props, 'children'> &
        VariantProps<typeof radioGroupItemVariants> & {
            /** Disables the item and says why in a tooltip. */
            disabledReason?: React.ReactNode
            /** The label. It wraps the radio, so the label also selects it and shows the disabled reason. */
            children?: React.ReactNode
        }
>(function RadioGroupItem({ className, size = 'default', disabled, disabledReason, children, ...props }, ref) {
    const { rootProps, wrap } = useDisabledControl({
        disabled,
        disabledReason,
        label: children,
        ariaDescribedBy: props['aria-describedby'],
    })
    return wrap(
        <RadioPrimitive.Root
            ref={ref}
            data-slot="radio-group-item"
            className={cn(radioGroupItemVariants({ size }), className)}
            {...props}
            {...rootProps}
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
