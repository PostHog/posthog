import * as React from 'react'

import { cn } from './lib/utils'

function Label({ className, ...props }: React.ComponentProps<'label'>): React.ReactElement {
    return (
        <label
            data-quill
            data-slot="label"
            className={cn(
                'flex items-center gap-2 text-xs/relaxed leading-none font-medium select-none group-has-[>[role=checkbox]]/field:cursor-pointer group-data-[disabled=true]:pointer-events-none group-data-[disabled=true]:opacity-50 peer-disabled:cursor-not-allowed peer-disabled:opacity-50',
                className
            )}
            {...props}
        />
    )
}

export { Label }
