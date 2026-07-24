import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import './button-group.css'
import { cn } from './lib/utils'
import { Separator } from './separator'

const buttonGroupVariants = cva('quill-button-group', {
    variants: {
        orientation: {
            horizontal: '',
            vertical: '',
        },
    },
    defaultVariants: {
        orientation: 'horizontal',
    },
})

function ButtonGroup({
    className,
    orientation = 'horizontal',
    ...props
}: React.ComponentProps<'div'> & VariantProps<typeof buttonGroupVariants>): React.ReactElement {
    return (
        <div
            role="group"
            data-quill
            data-slot="button-group"
            data-orientation={orientation}
            className={cn(buttonGroupVariants({ orientation }), className)}
            {...props}
        />
    )
}

function ButtonGroupText({ className, render, ...props }: useRender.ComponentProps<'div'>): React.ReactElement {
    return useRender({
        defaultTagName: 'div',
        props: mergeProps<'div'>(
            {
                className: cn('quill-button-group__text flex items-center gap-2', className),
            } as Omit<React.ComponentProps<'div'>, 'ref'>,
            props
        ),
        render,
        state: {
            slot: 'button-group-text',
        },
    })
}

function ButtonGroupSeparator({
    className,
    orientation = 'vertical',
    ...props
}: React.ComponentProps<typeof Separator>): React.ReactElement {
    return (
        <Separator
            data-slot="button-group-separator"
            orientation={orientation}
            className={cn('quill-button-group__separator', className)}
            {...props}
        />
    )
}

export { ButtonGroup, ButtonGroupSeparator, ButtonGroupText, buttonGroupVariants }
