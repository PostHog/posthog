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
            className={cn('quill-card-group group/card-group', className)}
            {...props}
        />
    )
}

export { CardGroup }
