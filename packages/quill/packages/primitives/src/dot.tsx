import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from './lib/utils'

const dotVariants = cva(
    'group/dot relative inline-flex p-0.5 shrink-0 items-center justify-center rounded-full border border-transparent font-medium whitespace-nowrap transition-all',
    {
        variants: {
            variant: {
                default: 'text-accent [&_[data-slot=dot-inner]]:bg-accent-foreground/40 [&_[data-slot=dot-pulse]]:border-accent-foreground/40',
                info: 'text-info [&_[data-slot=dot-inner]]:bg-info-foreground [&_[data-slot=dot-pulse]]:border-info-foreground',
                destructive: 'text-destructive [&_[data-slot=dot-inner]]:bg-destructive-foreground [&_[data-slot=dot-pulse]]:border-destructive-foreground',
                warning: 'text-warning [&_[data-slot=dot-inner]]:bg-warning-foreground [&_[data-slot=dot-pulse]]:border-warning-foreground',
                success: 'text-success [&_[data-slot=dot-inner]]:bg-success-foreground [&_[data-slot=dot-pulse]]:border-success-foreground',
            },
            pulse: {
                true: '',
                false: '',
            },
        },
        defaultVariants: {
            variant: 'default',
        },
    }
)

function Dot({
    className,
    variant = 'default',
    pulse = false,
    ...props
}: React.ComponentProps<'span'> & VariantProps<typeof dotVariants>): React.ReactElement {
    return (
        <span data-quill data-slot="dot" className={cn(dotVariants({ variant, pulse }), className)} {...props}>
            {pulse && (
                <span
                    aria-hidden
                    data-slot="dot-pulse"
                    className="pointer-events-none absolute inset-px rounded-full border-[.5px] border-current motion-safe:animate-radar motion-reduce:hidden bg-transparent"
                />
            )}
            <span data-slot="dot-inner" className={cn('rounded-full size-2 ', pulse && 'motion-safe:animate-pulse [animation-duration:.5s] [animation-delay:-2s]')} />
        </span>
    )
}

export { Dot, dotVariants }
