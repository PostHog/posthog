import * as React from 'react'

import { buttonVariants } from './button'
import { cn } from './lib/utils'

function MenuEmpty({ className, children, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            {...props}
            data-slot="menu-empty"
            role="status"
            aria-live="polite"
            className={cn(buttonVariants({ size: 'row', left: true, inert: true }), className)}
        >
            {children}
        </div>
    )
}

export { MenuEmpty }
