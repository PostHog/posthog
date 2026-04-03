import { IconSpinner } from '@posthog/icons'
import * as React from 'react'

import { cn } from './lib/utils'

function Spinner({ className, ...props }: React.ComponentProps<'svg'>): React.ReactElement {
    return (
        <IconSpinner role="status" aria-label="Loading" className={cn('size-4 animate-spin', className)} {...props} />
    )
}

export { Spinner }
