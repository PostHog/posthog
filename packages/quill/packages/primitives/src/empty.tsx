import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import './empty.css'
import { cn } from './lib/utils'

function Empty({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-quill
            data-slot="empty"
            className={cn(
                'quill-empty flex w-full min-w-0 flex-1 flex-col items-center justify-center gap-4',
                className
            )}
            {...props}
        />
    )
}

function EmptyHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="empty-header"
            className={cn('flex max-w-sm flex-col items-center gap-1', className)}
            {...props}
        />
    )
}

const emptyMediaVariants = cva('quill-empty__media flex shrink-0 items-center justify-center', {
    variants: {
        variant: {
            default: 'quill-empty__media--variant-default',
            icon: 'quill-empty__media--variant-icon',
        },
    },
    defaultVariants: {
        variant: 'default',
    },
})

function EmptyMedia({
    className,
    variant = 'default',
    ...props
}: React.ComponentProps<'div'> & VariantProps<typeof emptyMediaVariants>): React.ReactElement {
    return (
        <div
            data-slot="empty-icon"
            data-variant={variant}
            className={cn(emptyMediaVariants({ variant, className }))}
            {...props}
        />
    )
}

function EmptyTitle({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="empty-title" className={cn('quill-empty__title', className)} {...props} />
}

function EmptyDescription({ className, ...props }: React.ComponentProps<'p'>): React.ReactElement {
    return <div data-slot="empty-description" className={cn('quill-empty__description', className)} {...props} />
}

function EmptyContent({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="empty-content"
            className={cn('quill-empty__content flex w-full max-w-sm min-w-0 flex-col items-center gap-2', className)}
            {...props}
        />
    )
}

export { Empty, EmptyHeader, EmptyTitle, EmptyDescription, EmptyContent, EmptyMedia }
