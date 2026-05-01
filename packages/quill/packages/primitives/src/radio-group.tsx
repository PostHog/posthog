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

function RadioIndicator({
    checked,
    className,
    size = 'default',
}: { checked?: boolean; className?: string } & VariantProps<typeof radioIndicatorVariants>): React.ReactElement {
    return (
        <span
            data-slot="radio-indicator"
            className={cn(radioIndicatorVariants({ size }), checked && 'quill-radio-indicator--checked', className)}
        >
            {checked && <span className={radioDotVariants({ size })} />}
        </span>
    )
}

function RadioGroup({ className, ...props }: RadioGroupPrimitive.Props): React.ReactElement {
    return (
        <RadioGroupPrimitive
            data-quill
            data-slot="radio-group"
            className={cn('grid w-full gap-3', className)}
            {...props}
        />
    )
}

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

function RadioGroupItem({
    className,
    size = 'default',
    ...props
}: RadioPrimitive.Root.Props & VariantProps<typeof radioGroupItemVariants>): React.ReactElement {
    return (
        <RadioPrimitive.Root
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
}

export { RadioGroup, RadioGroupItem, RadioIndicator }
