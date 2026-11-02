import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import './empty.css'
import { cn } from './lib/utils'

const Empty = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function Empty(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-quill
            data-slot="empty"
            className={cn(
                'quill-empty flex w-full min-w-0 flex-1 flex-col items-center justify-center gap-4',
                className
            )}
            {...props}
        />
    )
})

const EmptyHeader = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function EmptyHeader(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="empty-header"
            className={cn('flex max-w-sm flex-col items-center gap-1', className)}
            {...props}
        />
    )
})

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

const EmptyMedia = React.forwardRef<
    HTMLDivElement,
    React.ComponentProps<'div'> & VariantProps<typeof emptyMediaVariants>
>(function EmptyMedia({ className, variant = 'default', ...props }, ref) {
    return (
        <div
            ref={ref}
            data-slot="empty-icon"
            data-variant={variant}
            className={cn(emptyMediaVariants({ variant, className }))}
            {...props}
        />
    )
})

const EmptyTitle = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function EmptyTitle(
    { className, ...props },
    ref
) {
    return <div ref={ref} data-slot="empty-title" className={cn('quill-empty__title', className)} {...props} />
})

const EmptyDescription = React.forwardRef<HTMLDivElement, React.ComponentProps<'p'>>(function EmptyDescription(
    { className, ...props },
    ref
) {
    return (
        <div ref={ref} data-slot="empty-description" className={cn('quill-empty__description', className)} {...props} />
    )
})

const EmptyContent = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function EmptyContent(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="empty-content"
            className={cn('quill-empty__content flex w-full max-w-sm min-w-0 flex-col items-center gap-2', className)}
            {...props}
        />
    )
})

export { Empty, EmptyHeader, EmptyTitle, EmptyDescription, EmptyContent, EmptyMedia }
