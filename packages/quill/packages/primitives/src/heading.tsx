import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from './lib/utils'

// Visual size is decoupled from the semantic element. Pick `size` for looks
// and `render` (e.g. <h1 />) for document outline / accessibility.
const headingVariants = cva('text-foreground font-semibold text-balance', {
    variants: {
        size: {
            '2xl': 'text-2xl tracking-tight',
            xl: 'text-xl tracking-tight',
            lg: 'text-lg',
            base: 'text-base',
            sm: 'text-sm',
        },
    },
    defaultVariants: {
        size: 'lg',
    },
})

function Heading({
    className,
    size = 'lg',
    render,
    ...props
}: useRender.ComponentProps<'h2'> & VariantProps<typeof headingVariants>): React.ReactElement {
    return useRender({
        defaultTagName: 'h2',
        props: mergeProps<'h2'>(
            {
                'data-quill': '',
                className: cn(headingVariants({ size }), className),
            } as Omit<React.ComponentProps<'h2'>, 'ref'>,
            props
        ),
        render,
        state: {
            slot: 'heading',
            size,
        },
    })
}

export { Heading, headingVariants }
