import * as React from 'react'

import { buttonVariants } from './button'
import './kbd.css'
import { cn } from './lib/utils'

const Kbd = React.forwardRef<HTMLElement, React.ComponentProps<'kbd'>>(function Kbd({ className, ...props }, ref) {
    return (
        <kbd
            ref={ref}
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
})

const KbdText = React.forwardRef<HTMLElement, React.ComponentProps<'span'>>(function KbdText(
    { className, ...props },
    ref
) {
    return (
        <kbd
            ref={ref}
            data-slot="kbd-text"
            className={cn('quill-kbd-text inline-flex w-fit items-center justify-center gap-1', className)}
            {...props}
        />
    )
})

const KbdGroup = React.forwardRef<HTMLElement, React.ComponentProps<'div'>>(function KbdGroup(
    { className, ...props },
    ref
) {
    return (
        <kbd ref={ref} data-slot="kbd-group" className={cn('inline-flex items-center gap-1', className)} {...props} />
    )
})

export { Kbd, KbdGroup, KbdText }
