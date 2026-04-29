import * as React from 'react'

import './card.css'
import { cn } from './lib/utils'

function Card({
    className,
    size = 'default',
    ...props
}: React.ComponentProps<'div'> & { size?: 'default' | 'sm' }): React.ReactElement {
    return (
        <div
            data-quill
            data-slot="card"
            data-size={size}
            className={cn('quill-card group/card flex flex-col', className)}
            {...props}
        />
    )
}

function CardHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="card-header"
            className={cn('quill-card__header group/card-header', className)}
            {...props}
        />
    )
}

const CardTitle = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(({ className, ...props }, ref) => (
    <div ref={ref} data-slot="card-title" className={cn('quill-card__title', className)} {...props} />
))
CardTitle.displayName = 'CardTitle'

function CardDescription({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="card-description" className={cn('quill-card__description', className)} {...props} />
}

function CardAction({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="card-action" className={cn('quill-card__action', className)} {...props} />
}

function CardContent({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="card-content" className={cn('quill-card__content', className)} {...props} />
}

function CardFooter({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="card-footer" className={cn('quill-card__footer', className)} {...props} />
}

export { Card, CardHeader, CardFooter, CardTitle, CardAction, CardDescription, CardContent }
