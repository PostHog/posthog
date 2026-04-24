import * as React from 'react'

import { buttonVariants } from './button'
import { cn } from './lib/utils'

function Kbd({ className, ...props }: React.ComponentProps<'kbd'>): React.ReactElement {
    return (
        <kbd
            data-quill
            data-slot="kbd"
            className={cn(
                buttonVariants({ variant: 'outline', size: 'xs' }),
                "pointer-events-none inline-flex h-5 w-fit min-w-5 items-center px-1 justify-center gap-1 rounded-[0.25rem] font-sans text-[0.625rem] font-medium select-none in-data-[slot=tooltip-content]:bg-background/20 in-data-[slot=tooltip-content]:text-background dark:in-data-[slot=tooltip-content]:bg-background/10 [&_svg:not([class*='size-'])]:size-3",
                className
            )}
            {...props}
        />
    )
}
function KbdText({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return (
        <kbd
            data-slot="kbd-text"
            className={cn(
                "-mx-1 text-muted-foreground pointer-events-none inline-flex w-fit items-center px-1 justify-center gap-1 rounded-[0.25rem] font-sans text-[0.625rem] font-medium select-none in-data-[slot=tooltip-content]:bg-background/20 in-data-[slot=tooltip-content]:text-background dark:in-data-[slot=tooltip-content]:bg-background/10 [&_svg:not([class*='size-'])]:size-3",
                className
            )}
            {...props}
        />
    )
}

function KbdGroup({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <kbd data-slot="kbd-group" className={cn('inline-flex items-center gap-1', className)} {...props} />
}

export { Kbd, KbdGroup, KbdText }
