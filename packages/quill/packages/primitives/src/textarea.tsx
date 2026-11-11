import * as React from 'react'

import './textarea.css'
import { cn } from './lib/utils'

const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<'textarea'>>(function Textarea(
    { className, ...props },
    ref
) {
    return (
        <textarea
            ref={ref}
            data-quill
            data-slot="textarea"
            className={cn('quill-textarea flex', className)}
            {...props}
        />
    )
})

export { Textarea }
