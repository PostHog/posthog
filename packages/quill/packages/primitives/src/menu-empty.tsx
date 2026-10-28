import * as React from 'react'

import { buttonVariants } from './button'
import { cn } from './lib/utils'

const MenuEmpty = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function MenuEmpty(
    { className, children, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            {...props}
            data-slot="menu-empty"
            role="status"
            aria-live="polite"
            className={cn(buttonVariants({ size: 'row', left: true, inert: true }), className)}
        >
            {children}
        </div>
    )
})

export { MenuEmpty }
