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
            className={cn(
                buttonVariants({ size: 'sm', left: true, inert: true }),
                'font-normal w-full h-7', 
                className
            )}
        >
            {children}
        </div>
    )
}

export { MenuEmpty }
