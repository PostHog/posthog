import * as React from 'react'

import './label.css'
import { cn } from './lib/utils'

function Label({ className, ...props }: React.ComponentProps<'label'>): React.ReactElement {
    return (
        <label
            data-quill
            data-slot="label"
            className={cn('quill-label flex items-center gap-2', className)}
            {...props}
        />
    )
}

export { Label }
