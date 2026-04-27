import * as React from 'react'

import { buttonVariants } from './button'
import './kbd.css'
import { cn } from './lib/utils'

function Kbd({ className, ...props }: React.ComponentProps<'kbd'>): React.ReactElement {
    return (
        <kbd
            data-quill
            data-slot="kbd"
            className={cn(
                buttonVariants({ variant: 'outline', size: 'xs' }),
                'quill-kbd inline-flex w-fit items-center justify-center gap-1',
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
            className={cn('quill-kbd-text inline-flex w-fit items-center justify-center gap-1', className)}
            {...props}
        />
    )
}

function KbdGroup({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <kbd data-slot="kbd-group" className={cn('inline-flex items-center gap-1', className)} {...props} />
}

export { Kbd, KbdGroup, KbdText }
