import { type VariantProps } from 'class-variance-authority'
import { XIcon } from 'lucide-react'
import * as React from 'react'

import { Button, type buttonVariants } from './button'
import { ButtonGroup, type buttonGroupVariants } from './button-group'
import './chip.css'
import { cn } from './lib/utils'

type ChipProps = Omit<React.ComponentProps<typeof Button>, 'variant'> &
    Omit<VariantProps<typeof buttonVariants>, 'variant'>

/*
 * Chip renders a <div>, not a <button>. A Chip commonly contains a nested
 * ChipClose (which IS a button), and <button> inside <button> is invalid HTML —
 * browsers reparent the inner button outside the outer one, which also breaks
 * `.quill-chip:has([data-slot='chip-close'])` because chip-close is no longer
 * a descendant. Styling still flows through `.quill-button` variants because
 * those rules are tag-agnostic (class-based).
 */
const Chip = React.forwardRef<HTMLDivElement, ChipProps>(
    ({ className, size = 'sm', children, ...props }, ref) => {
        return (
            <Button
                ref={ref as React.Ref<HTMLButtonElement>}
                render={<div />}
                data-quill
                data-slot="chip"
                size={size}
                variant="outline"
                className={cn('quill-chip gap-1', className)}
                {...props}
            >
                {children}
            </Button>
        )
    }
)
Chip.displayName = 'Chip'

const ChipClose = React.forwardRef<HTMLButtonElement, React.ComponentProps<typeof Button>>(
    ({ className, children, ...props }, ref) => {
        return (
            <Button
                ref={ref}
                data-slot="chip-close"
                size="icon-xs"
                className={cn('quill-chip-close rounded-xs', className)}
                {...props}
            >
                {children ?? <XIcon />}
            </Button>
        )
    }
)
ChipClose.displayName = 'ChipClose'

function ChipGroup({
    className,
    ...props
}: React.ComponentProps<typeof ButtonGroup> & VariantProps<typeof buttonGroupVariants>): React.ReactElement {
    return <ButtonGroup data-slot="chip-group" className={cn('flex-wrap gap-0', className)} {...props} />
}

export { Chip, ChipClose, ChipGroup }
