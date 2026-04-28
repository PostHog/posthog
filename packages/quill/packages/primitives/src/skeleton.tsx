import * as React from 'react'

import './skeleton.css'
import { cn } from './lib/utils'

function Skeleton({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-quill
            data-slot="skeleton"
            className={cn('quill-skeleton', className)}
            {...props}
        />
    )
}

export { Skeleton }
