import { Radio as RadioPrimitive } from '@base-ui/react/radio'
import { RadioGroup as RadioGroupPrimitive } from '@base-ui/react/radio-group'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from './lib/utils'

const radioIndicatorVariants = cva('relative flex shrink-0 rounded-full border border-accent', {
    variants: {
        size: {
            default: 'size-4',
            sm: 'size-3.5',
        },
    },
    defaultVariants: {
        size: 'default',
    },
})

const radioDotVariants = cva(
    'absolute top-1/2 start-1/2 -translate-x-1/2 rtl:translate-x-1/2 -translate-y-1/2 rounded-full bg-primary-foreground',
    {
        variants: {
            size: {
                default: 'size-2',
                sm: 'size-1.5',
            },
        },
        defaultVariants: {
            size: 'default',
        },
    }
)

function RadioIndicator({
    checked,
    className,
    size = 'default',
}: { checked?: boolean; className?: string } & VariantProps<typeof radioIndicatorVariants>): React.ReactElement {
    return (
        <span
            data-slot="radio-indicator"
            className={cn(
                radioIndicatorVariants({ size }),
                checked && 'border-primary bg-primary text-primary-foreground',
                className
            )}
        >
            {checked && <span className={radioDotVariants({ size })} />}
        </span>
    )
}

function RadioGroup({ className, ...props }: RadioGroupPrimitive.Props): React.ReactElement {
    return <RadioGroupPrimitive data-slot="radio-group" className={cn('grid w-full gap-3', className)} {...props} />
}

const radioGroupItemVariants = cva(
    'group/radio-group-item peer relative flex aspect-square shrink-0 rounded-full border border-input outline-none after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:destructive-foreground/50 aria-invalid:border-destructive-foreground/50 aria-invalid:aria-checked:border-primary dark:bg-input/30 data-checked:border-primary data-checked:bg-primary data-checked:text-primary-foreground dark:data-checked:bg-primary',
    {
        variants: {
            size: {
                default: 'size-4',
                sm: 'size-3.5',
            },
        },
        defaultVariants: {
            size: 'default',
        },
    }
)

const radioGroupItemIndicatorVariants = cva('flex items-center justify-center', {
    variants: {
        size: {
            default: 'size-4',
            sm: 'size-3.5',
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
