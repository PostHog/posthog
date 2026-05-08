import * as React from 'react'

import './textarea.css'
import { cn } from './lib/utils'

function Textarea({ className, ...props }: React.ComponentProps<'textarea'>): React.ReactElement {
    return (
        <textarea
            data-quill
            data-slot="textarea"
            className={cn('quill-textarea flex', className)}
            {...props}
        />
    )
}

export { Textarea }
