import { Loader2Icon } from 'lucide-react'
import * as React from 'react'

import './spinner.css'
import { cn } from './lib/utils'

function Spinner({ className, ...props }: React.ComponentProps<'svg'>): React.ReactElement {
    return (
        <Loader2Icon data-quill role="status" aria-label="Loading" className={cn('quill-spinner', className)} {...props} />
    )
}

export { Spinner }
