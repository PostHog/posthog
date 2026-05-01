import * as React from 'react'

import { buttonVariants } from './button'
import { cn } from './lib/utils'
import './menu-empty.css'

function MenuEmpty({ className, children, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            {...props}
            data-slot="menu-empty"
            role="status"
            aria-live="polite"
            className={cn(buttonVariants({ size: 'sm', left: true, inert: true }), 'quill-menu-empty', className)}
        >
            {children}
        </div>
    )
}

export { MenuEmpty }
