import './card.css'

import * as React from 'react'

import { cn } from './lib/utils'

const Card = React.forwardRef<
    HTMLDivElement,
    React.ComponentProps<'div'> & { size?: 'default' | 'sm'; flush?: boolean }
>(function Card({ className, size = 'default', flush = false, ...props }, ref) {
    return (
        <div
            ref={ref}
            data-quill
            data-slot="card"
            data-size={size}
            data-flush={flush ? '' : undefined}
            className={cn('quill-card group/card flex flex-col', className)}
            {...props}
        />
    )
})

const CardHeader = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function CardHeader(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="card-header"
            className={cn('quill-card__header group/card-header', className)}
            {...props}
        />
    )
})

const CardTitle = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(({ className, ...props }, ref) => (
    <div ref={ref} data-slot="card-title" className={cn('quill-card__title', className)} {...props} />
))
CardTitle.displayName = 'CardTitle'

const CardDescription = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function CardDescription(
    { className, ...props },
    ref
) {
    return (
        <div ref={ref} data-slot="card-description" className={cn('quill-card__description', className)} {...props} />
    )
})

const CardAction = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function CardAction(
    { className, ...props },
    ref
) {
    return <div ref={ref} data-slot="card-action" className={cn('quill-card__action', className)} {...props} />
})

const CardContent = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function CardContent(
    { className, ...props },
    ref
) {
    return <div ref={ref} data-slot="card-content" className={cn('quill-card__content', className)} {...props} />
})

const CardFooter = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function CardFooter(
    { className, ...props },
    ref
) {
    return <div ref={ref} data-slot="card-footer" className={cn('quill-card__footer', className)} {...props} />
})

export { Card, CardHeader, CardFooter, CardTitle, CardAction, CardDescription, CardContent }
