import { Toggle as TogglePrimitive } from '@base-ui/react/toggle'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from './lib/utils'

const toggleVariants = cva(
    "group/toggle inline-flex items-center justify-center gap-1 rounded-sm text-xs font-medium whitespace-nowrap transition-all outline-none hover:bg-muted hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 aria-pressed:bg-accent data-[state=on]:bg-accent dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
    {
        variants: {
            variant: {
                default: 'bg-transparent',
                outline: 'border border-input bg-transparent hover:bg-muted',
            },
            size: {
                default: 'h-7 min-w-7 px-2',
                sm: "h-6 min-w-6 rounded-[min(var(--radius-sm),6px)] px-1.5 text-[0.625rem] [&_svg:not([class*='size-'])]:size-3",
                lg: 'h-8 min-w-8 px-2',
                icon: "h-7 min-w-7 rounded-[min(var(--radius-sm),6px)] px-1.5 text-[0.625rem] [&_svg:not([class*='size-'])]:size-3",
            },
        },
        defaultVariants: {
            variant: 'default',
            size: 'default',
        },
    }
)

function Toggle({
    className,
    variant = 'default',
    size = 'default',
    ...props
}: TogglePrimitive.Props & VariantProps<typeof toggleVariants>): React.ReactElement {
    return (
        <TogglePrimitive data-quill data-slot="toggle" className={cn(toggleVariants({ variant, size, className }))} {...props} />
    )
}

export { Toggle, toggleVariants }
