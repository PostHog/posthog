import { Checkbox as CheckboxPrimitive } from '@base-ui/react/checkbox'
import { CheckIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from './lib/utils'

function CheckboxIndicator({ checked, className }: { checked?: boolean; className?: string }): React.ReactElement {
    return (
        <span
            data-slot="checkbox-indicator"
            className={cn(
                'flex size-4 shrink-0 items-center justify-center rounded-[4px] border border-input',
                checked && 'border-primary bg-primary text-primary-foreground',
                className
            )}
        >
            {checked && <CheckIcon className="size-3" />}
        </span>
    )
}

function Checkbox({ className, ...props }: CheckboxPrimitive.Root.Props): React.ReactElement {
    return (
        <CheckboxPrimitive.Root
            data-slot="checkbox"
            className={cn(
                'peer relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border border-input transition-shadow outline-none group-has-disabled/field:opacity-50 after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-2 aria-invalid:ring-destructive/20 aria-invalid:aria-checked:border-primary dark:bg-input/30 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 data-checked:border-primary data-checked:bg-primary data-checked:text-primary-foreground dark:data-checked:bg-primary not-disabled:cursor-pointer hover:border-ring/50',
                className
            )}
            {...props}
        >
            <CheckboxPrimitive.Indicator
                data-slot="checkbox-primitive-indicator"
                className="grid place-content-center text-current transition-none"
            >
                <CheckboxIndicator checked className="border-none bg-transparent" />
            </CheckboxPrimitive.Indicator>
        </CheckboxPrimitive.Root>
    )
}

export { Checkbox, CheckboxIndicator }
