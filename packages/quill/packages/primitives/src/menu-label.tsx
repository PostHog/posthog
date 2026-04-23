import * as React from 'react'

import { cn } from './lib/utils'

function MenuLabel({ className, ...props }: React.ComponentProps<'label'>): React.ReactElement {
    return (
        <label
            data-quill
            data-slot="menu-label"
            className={cn(
                'px-2 py-1.5 text-muted-foreground/50 dark:text-muted-foreground/80 uppercase font-semibold text-xxs leading-5 tracking-[0.075em]',
                className
            )}
            {...props}
        />
    )
}

export { MenuLabel }
