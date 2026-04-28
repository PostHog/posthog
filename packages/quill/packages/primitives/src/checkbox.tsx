import { Checkbox as CheckboxPrimitive } from '@base-ui/react/checkbox'
import { cva, type VariantProps } from 'class-variance-authority'
import { CheckIcon } from 'lucide-react'
import * as React from 'react'

import './checkbox.css'
import { cn } from './lib/utils'

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

function CheckboxIndicator({
    checked,
    className,
    size = 'default',
}: { checked?: boolean; className?: string } & VariantProps<typeof checkboxIndicatorVariants>): React.ReactElement {
    return (
        <span
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
}

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

function Checkbox({
    className,
    size = 'default',
    ...props
}: CheckboxPrimitive.Root.Props & VariantProps<typeof checkboxVariants>): React.ReactElement {
    return (
        <CheckboxPrimitive.Root
            data-quill
            data-slot="checkbox"
            className={cn(checkboxVariants({ size }), className)}
            {...props}
        >
            <CheckboxPrimitive.Indicator
                data-slot="checkbox-primitive-indicator"
                className="grid place-content-center text-current transition-none"
            >
                <CheckboxIndicator checked size={size ?? 'default'} className="border-none bg-transparent" />
            </CheckboxPrimitive.Indicator>
        </CheckboxPrimitive.Root>
    )
}

export { Checkbox, CheckboxIndicator }
