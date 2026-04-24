import * as React from 'react'

import { cn } from './lib/utils'

function Textarea({ className, ...props }: React.ComponentProps<'textarea'>): React.ReactElement {
    return (
        <textarea
            data-quill
            data-slot="textarea"
            className={cn(
                'flex field-sizing-content min-h-16 w-full text-xs resize-none rounded-sm border border-input bg-input/20 px-2 py-2 transition-colors outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:bg-destructive/50 aria-invalid:border-destructive-foreground/30 focus-visible:aria-invalid:ring-3 aria-invalid:ring-destructive-foreground/50',
                className
            )}
            {...props}
        />
    )
}

export { Textarea }
