import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import './badge.css'
import { cn } from './lib/utils'

const badgeVariants = cva(
    'quill-badge inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden whitespace-nowrap',
    {
        variants: {
            variant: {
                default: 'quill-badge--variant-default',
                info: 'quill-badge--variant-info',
                destructive: 'quill-badge--variant-destructive',
                warning: 'quill-badge--variant-warning',
                success: 'quill-badge--variant-success',
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
            } as Omit<React.ComponentProps<'span'>, 'ref'>,
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
