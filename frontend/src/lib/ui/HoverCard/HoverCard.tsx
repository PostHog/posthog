import * as HoverCardPrimitive from '@radix-ui/react-hover-card'
import * as React from 'react'

import { cn } from 'lib/utils/css-classes'

function HoverCard({ ...props }: React.ComponentProps<typeof HoverCardPrimitive.Root>): JSX.Element {
    return <HoverCardPrimitive.Root data-slot="hover-card" {...props} />
}
function HoverCardTrigger({ ...props }: React.ComponentProps<typeof HoverCardPrimitive.Trigger>): JSX.Element {
    return <HoverCardPrimitive.Trigger data-slot="hover-card-trigger" {...props} />
}
function HoverCardContent({
    className,
    align = 'center',
    sideOffset = 4,
    ...props
}: React.ComponentProps<typeof HoverCardPrimitive.Content>): JSX.Element {
    return (
        <HoverCardPrimitive.Portal data-slot="hover-card-portal">
            <HoverCardPrimitive.Content
                data-slot="hover-card-content"
                align={align}
                sideOffset={sideOffset}
                className={cn(
                    'bg-surface-popover text-primary z-[var(--z-popover)] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 w-64 origin-(--radix-hover-card-content-transform-origin) rounded border p-4 shadow outline-hidden',
                    className
                )}
                {...props}
            />
        </HoverCardPrimitive.Portal>
    )
}
export { HoverCard, HoverCardTrigger, HoverCardContent }
