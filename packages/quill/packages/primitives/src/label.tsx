import * as React from 'react'

import './label.css'
import { cn } from './lib/utils'

const Label = React.forwardRef<HTMLLabelElement, React.ComponentProps<'label'>>(function Label(
    { className, ...props },
    ref
) {
    return (
        <label
            ref={ref}
            data-quill
            data-slot="label"
            className={cn('quill-label flex items-center gap-2', className)}
            {...props}
        />
    )
})

export { Label }
