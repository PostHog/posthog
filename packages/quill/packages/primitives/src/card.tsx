import * as React from 'react'

import { cn } from './lib/utils'

function Card({
    className,
    size = 'default',
    ...props
}: React.ComponentProps<'div'> & { size?: 'default' | 'sm' }): React.ReactElement {
    return (
        <div
            data-slot="card"
            data-size={size}
            className={cn(
                'group/card flex flex-col gap-6 overflow-hidden rounded-lg bg-card py-6 text-xs/relaxed text-card-foreground ring-1 ring-foreground/10 has-[>img:first-child]:pt-0 data-[size=sm]:gap-4 data-[size=sm]:py-4 *:[img:first-child]:rounded-t-lg *:[img:last-child]:rounded-b-lg has-data-[slot=card-footer]:pb-0',
                className
            )}
            {...props}
        />
    )
}

function CardHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="card-header"
            className={cn(
                'group/card-header @container/card-header grid auto-rows-min items-start gap-1.5 rounded-t-lg px-6 group-data-[size=sm]/card:px-4 has-data-[slot=card-action]:grid-cols-[1fr_auto] has-data-[slot=card-description]:grid-rows-[auto_auto] [.border-b]:pb-6 group-data-[size=sm]/card:[.border-b]:pb-4',
                className
            )}
            {...props}
        />
    )
}

const CardTitle = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(({ className, ...props }, ref) => (
    <div ref={ref} data-slot="card-title" className={cn('text-sm font-medium', className)} {...props} />
))
CardTitle.displayName = 'CardTitle'

function CardDescription({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="card-description"
            className={cn('text-xs/relaxed text-muted-foreground', className)}
            {...props}
        />
    )
}

function CardAction({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="card-action"
            className={cn('col-start-2 row-span-2 row-start-1 self-start justify-self-end', className)}
            {...props}
        />
    )
}

function CardContent({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="card-content" className={cn('px-6 group-data-[size=sm]/card:px-4', className)} {...props} />
}

function CardFooter({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="card-footer"
            className={cn(
                'bg-muted/30 flex items-center border-t rounded-b-lg px-6 py-6 group-data-[size=sm]/card:px-4 group-data-[size=sm]/card:py-4',
                className
            )}
            {...props}
        />
    )
}

export { Card, CardHeader, CardFooter, CardTitle, CardAction, CardDescription, CardContent }
