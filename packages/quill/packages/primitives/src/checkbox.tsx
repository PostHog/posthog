import { Checkbox as CheckboxPrimitive } from '@base-ui/react/checkbox'
import { cva, type VariantProps } from 'class-variance-authority'
import { CheckIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from './lib/utils'

const checkboxIndicatorVariants = cva('flex shrink-0 items-center justify-center border border-accent', {
    variants: {
        size: {
            default: 'size-4 rounded-[4px]',
            sm: 'size-3.5 rounded-[3px]',
        },
    },
    defaultVariants: {
        size: 'default',
    },
})

const checkIconVariants = cva('', {
    variants: {
        size: {
            default: 'size-3',
            sm: 'size-2.5',
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
                checked && 'border-primary bg-primary text-primary-foreground',
                className
            )}
        >
            {checked && <CheckIcon className={checkIconVariants({ size })} />}
        </span>
    )
}

const checkboxVariants = cva(
    'peer relative flex shrink-0 items-center justify-center border border-input transition-shadow outline-none group-has-disabled/field:opacity-50 after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 aria-invalid:aria-checked:border-primary dark:bg-input/30 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 data-checked:border-primary data-checked:bg-primary data-checked:text-primary-foreground dark:data-checked:bg-primary not-disabled:cursor-pointer hover:border-ring/50',
    {
        variants: {
            size: {
                default: 'size-4 rounded-[4px]',
                sm: 'size-3.5 rounded-[3px]',
            },
        },
        defaultVariants: {
            size: 'default',
        },
    }
)

function Checkbox({
    className,
    size = 'default',
    ...props
}: CheckboxPrimitive.Root.Props & VariantProps<typeof checkboxVariants>): React.ReactElement {
    return (
        <CheckboxPrimitive.Root
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
