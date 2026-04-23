import * as React from 'react'

import { cn } from './lib/utils'

function Skeleton({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-quill
            data-slot="skeleton"
            className={cn('animate-pulse rounded-md bg-accent [&_*]:opacity-0', className)}
            {...props}
        />
    )
}

export { Skeleton }
