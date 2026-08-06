import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from './lib/utils'

// Body / caption / label text. Defaults to a block <p>; pass render=<span /> for inline.
const textVariants = cva('', {
    variants: {
        size: {
            lg: 'text-lg',
            base: 'text-base',
            sm: 'text-sm',
            xs: 'text-xs',
            xxs: 'text-xxs',
        },
        variant: {
            default: 'text-foreground',
            muted: 'text-muted-foreground',
            destructive: 'text-destructive-foreground',
        },
        weight: {
            normal: 'font-normal',
            medium: 'font-medium',
            semibold: 'font-semibold',
        },
    },
    defaultVariants: {
        size: 'base',
        variant: 'default',
        weight: 'normal',
    },
})

function Text({
    className,
    size = 'base',
    variant = 'default',
    weight = 'normal',
    render,
    ...props
}: useRender.ComponentProps<'p'> & VariantProps<typeof textVariants>): React.ReactElement {
    return useRender({
        defaultTagName: 'p',
        props: mergeProps<'p'>(
            {
                'data-quill': '',
                className: cn(textVariants({ size, variant, weight }), className),
            } as Omit<React.ComponentProps<'p'>, 'ref'>,
            props
        ),
        render,
        state: {
            slot: 'text',
            size,
            variant,
            weight,
        },
    })
}

export { Text, textVariants }
