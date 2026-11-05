import './checkbox.css'

import { Checkbox as CheckboxPrimitive } from '@base-ui/react/checkbox'
import { cva, type VariantProps } from 'class-variance-authority'
import { CheckIcon, MinusIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from './lib/utils'
import { hasTooltipContent, withTooltip } from './with-tooltip'

const checkboxIndicatorVariants = cva('quill-checkbox-indicator flex shrink-0 items-center justify-center', {
    variants: {
        size: {
            default: 'quill-checkbox-indicator--size-default',
            sm: 'quill-checkbox-indicator--size-sm',
        },
    },
    defaultVariants: {
        size: 'default',
    },
})

const checkIconVariants = cva('', {
    variants: {
        size: {
            default: 'quill-checkbox-icon--size-default',
            sm: 'quill-checkbox-icon--size-sm',
        },
    },
    defaultVariants: {
        size: 'default',
    },
})

const CheckboxIndicator = React.forwardRef<
    HTMLSpanElement,
    { checked?: boolean; className?: string } & VariantProps<typeof checkboxIndicatorVariants>
>(function CheckboxIndicator({ checked, className, size = 'default' }, ref) {
    return (
        <span
            ref={ref}
            data-slot="checkbox-indicator"
            className={cn(
                checkboxIndicatorVariants({ size }),
                checked && 'quill-checkbox-indicator--checked',
                className
            )}
        >
            {checked && <CheckIcon className={checkIconVariants({ size })} />}
        </span>
    )
})

const checkboxVariants = cva('quill-checkbox peer flex shrink-0 items-center justify-center', {
    variants: {
        size: {
            default: 'quill-checkbox--size-default',
            sm: 'quill-checkbox--size-sm',
        },
    },
    defaultVariants: {
        size: 'default',
    },
})

const Checkbox = React.forwardRef<
    React.ComponentRef<typeof CheckboxPrimitive.Root>,
    CheckboxPrimitive.Root.Props &
        VariantProps<typeof checkboxVariants> & {
            /** Disables the checkbox and says why in a tooltip. */
            disabledReason?: React.ReactNode
        }
>(function Checkbox({ className, size = 'default', disabled, disabledReason, ...props }, ref) {
    return withTooltip(
        <CheckboxPrimitive.Root
            ref={ref}
            data-quill
            data-slot="checkbox"
            disabled={disabled || hasTooltipContent(disabledReason)}
            className={cn(checkboxVariants({ size }), className)}
            {...props}
        >
            <CheckboxPrimitive.Indicator
                data-slot="checkbox-primitive-indicator"
                className="grid place-content-center text-current transition-none"
            >
                {props.indeterminate ? (
                    <MinusIcon className={checkIconVariants({ size })} />
                ) : (
                    <CheckboxIndicator checked size={size ?? 'default'} className="border-none bg-transparent" />
                )}
            </CheckboxPrimitive.Indicator>
        </CheckboxPrimitive.Root>,
        disabledReason,
        { target: 'inline', focusable: hasTooltipContent(disabledReason) }
    )
})

export { Checkbox, CheckboxIndicator }
