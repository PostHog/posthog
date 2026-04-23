import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from './lib/utils'

const badgeVariants = cva(
    'group/badge inline-flex h-4 w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border border-transparent px-1.5 py-0.5 text-[0.625rem] font-medium whitespace-nowrap transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 has-data-[icon=inline-end]:pe-[calc(var(--spacing)*0.6)] has-data-[icon=inline-start]:ps-[calc(var(--spacing)*0.6)] aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-2.5!',
    {
        variants: {
            variant: {
                default: 'bg-accent text-accent-foreground',
                info: 'bg-info text-info-foreground',
                destructive: 'bg-destructive text-destructive-foreground',
                warning: 'bg-warning text-warning-foreground',
                success: 'bg-success text-success-foreground',
            },
        },
        defaultVariants: {
            variant: 'default',
        },
    }
)

function Badge({
    className,
    variant = 'default',
    render,
    ...props
}: useRender.ComponentProps<'span'> & VariantProps<typeof badgeVariants>): React.ReactElement {
    return useRender({
        defaultTagName: 'span',
        props: mergeProps<'span'>(
            {
                'data-quill': '',
                className: cn(badgeVariants({ variant }), className),
            },
            props
        ),
        render,
        state: {
            slot: 'badge',
            variant,
        },
    })
}

export { Badge, badgeVariants }
