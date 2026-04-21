import * as React from 'react'

import { Button, buttonVariants } from './button'
import { cn } from './lib/utils'

function MenuEmpty({ className, children, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            {...props}
            data-slot="menu-empty"
            role="alert"
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
