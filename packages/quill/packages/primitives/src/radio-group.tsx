import { Radio as RadioPrimitive } from '@base-ui/react/radio'
import { RadioGroup as RadioGroupPrimitive } from '@base-ui/react/radio-group'
import * as React from 'react'

import { cn } from './lib/utils'

function RadioIndicator({ checked, className }: { checked?: boolean; className?: string }): React.ReactElement {
    return (
        <span
            data-slot="radio-indicator"
            className={cn(
                'relative flex size-4 shrink-0 rounded-full border border-input',
                checked && 'border-primary bg-primary text-primary-foreground',
                className
            )}
        >
            {checked && (
                <span className="absolute top-1/2 start-1/2 size-2 -translate-x-1/2 rtl:translate-x-1/2 -translate-y-1/2 rounded-full bg-primary-foreground" />
            )}
        </span>
    )
}

function RadioGroup({ className, ...props }: RadioGroupPrimitive.Props): React.ReactElement {
    return <RadioGroupPrimitive data-slot="radio-group" className={cn('grid w-full gap-3', className)} {...props} />
}

function RadioGroupItem({ className, ...props }: RadioPrimitive.Root.Props): React.ReactElement {
    return (
        <RadioPrimitive.Root
            data-slot="radio-group-item"
            className={cn(
                'group/radio-group-item peer relative flex aspect-square size-4 shrink-0 rounded-full border border-input outline-none after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:destructive-foreground/50 aria-invalid:border-destructive-foreground/50 aria-invalid:aria-checked:border-primary dark:bg-input/30 data-checked:border-primary data-checked:bg-primary data-checked:text-primary-foreground dark:data-checked:bg-primary',
                className
            )}
            {...props}
        >
            <RadioPrimitive.Indicator
                data-slot="radio-group-indicator"
                className="flex size-4 items-center justify-center"
            >
                <span className="absolute top-1/2 start-1/2 size-2 -translate-x-1/2 rtl:translate-x-1/2 -translate-y-1/2 rounded-full bg-primary-foreground" />
            </RadioPrimitive.Indicator>
        </RadioPrimitive.Root>
    )
}

export { RadioGroup, RadioGroupItem, RadioIndicator }
