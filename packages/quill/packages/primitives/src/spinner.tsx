import { Loader2Icon } from 'lucide-react'
import * as React from 'react'

import './spinner.css'
import { cn } from './lib/utils'

const Spinner = React.forwardRef<React.ComponentRef<typeof Loader2Icon>, React.ComponentProps<'svg'>>(function Spinner(
    { className, ...props },
    ref
) {
    return (
        <Loader2Icon
            ref={ref}
            data-quill
            role="status"
            aria-label="Loading"
            className={cn('quill-spinner', className)}
            {...props}
        />
    )
})

export { Spinner }
