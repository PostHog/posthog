import * as React from 'react'

import { cn } from './lib/utils'

const CardGroup = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'> & { size?: 'default' | 'sm' }>(
    function CardGroup({ className, size = 'default', ...props }, ref) {
        return (
            <div
                ref={ref}
                data-quill
                data-slot="card-group"
                data-size={size}
                className={cn('quill-card-group group/card-group', className)}
                {...props}
            />
        )
    }
)

export { CardGroup }
