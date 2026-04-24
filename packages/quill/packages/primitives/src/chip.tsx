import { type VariantProps } from 'class-variance-authority'
import { XIcon } from 'lucide-react'
import * as React from 'react'

import { Button, type buttonVariants } from './button'
import { ButtonGroup, type buttonGroupVariants } from './button-group'
import { cn } from './lib/utils'

type ChipProps = React.ComponentProps<typeof Button> & VariantProps<typeof buttonVariants>

const Chip = React.forwardRef<HTMLButtonElement, ChipProps>(
    ({ className, size = 'sm', variant = 'outline', children, ...props }, ref) => {
        return (
            <Button
                ref={ref}
                data-quill
                data-slot="chip"
                size={size}
                variant={variant}
                className={cn('gap-1 rounded-sm has-data-[slot=chip-close]:pe-0 bg-background max-w-full focus-visible:border-ring/50 focus-visible:ring-3', className)}
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
                className={cn('opacity-50 hover:opacity-100', className)}
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
