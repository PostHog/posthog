import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import './dot.css'
import { cn } from './lib/utils'

const dotVariants = cva('quill-dot relative inline-flex p-0.5 shrink-0 items-center justify-center whitespace-nowrap', {
    variants: {
        variant: {
            default: 'quill-dot--variant-default',
            info: 'quill-dot--variant-info',
            destructive: 'quill-dot--variant-destructive',
            warning: 'quill-dot--variant-warning',
            success: 'quill-dot--variant-success',
        },
        pulse: {
            true: 'quill-dot--pulse',
            false: '',
        },
    },
    defaultVariants: {
        variant: 'default',
    },
})

function Dot({
    className,
    variant = 'default',
    pulse = false,
    ...props
}: React.ComponentProps<'span'> & VariantProps<typeof dotVariants>): React.ReactElement {
    return (
        <span
            data-quill
            data-slot="dot"
            className={cn(dotVariants({ variant, pulse }), className)}
            {...props}
        >
            {pulse && (
                <span
                    aria-hidden
                    data-slot="dot-pulse"
                    className="quill-dot__pulse pointer-events-none absolute inset-px"
                />
            )}
            <span data-slot="dot-inner" className="quill-dot__inner" />
        </span>
    )
}

export { Dot, dotVariants }
