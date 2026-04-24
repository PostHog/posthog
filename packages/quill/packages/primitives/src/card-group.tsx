import * as React from 'react'

import { cn } from './lib/utils'

function CardGroup({
    className,
    size = 'default',
    ...props
}: React.ComponentProps<'div'> & { size?: 'default' | 'sm' }): React.ReactElement {
    return (
        <div
            data-quill
            data-slot="card-group"
            data-size={size}
            className={cn(
                'group/card-group',
                // children card groups
                '[&>[data-slot=card-group]]:mb-4',
                // all cards
                '[&>[data-slot=card]]:rounded-none',
                // first card
                '[&>[data-slot=card]:first-child]:rounded-t-lg',
                // last card
                '[&>[data-slot=card]:last-child]:rounded-b-lg',
                className
            )}
            {...props}
        />
    )
}

export { CardGroup }
