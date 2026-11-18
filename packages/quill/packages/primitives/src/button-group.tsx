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

const ButtonGroup = React.forwardRef<
    HTMLDivElement,
    React.ComponentProps<'div'> & VariantProps<typeof buttonGroupVariants>
>(function ButtonGroup({ className, orientation = 'horizontal', ...props }, ref) {
    return (
        <div
            ref={ref}
            role="group"
            data-quill
            data-slot="button-group"
            data-orientation={orientation}
            className={cn(buttonGroupVariants({ orientation }), className)}
            {...props}
        />
    )
})

const ButtonGroupText = React.forwardRef<HTMLDivElement, useRender.ComponentProps<'div'>>(function ButtonGroupText(
    { className, render, ...props },
    ref
) {
    return useRender({
        ref,
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
})

const ButtonGroupSeparator = React.forwardRef<
    React.ComponentRef<typeof Separator>,
    React.ComponentProps<typeof Separator>
>(function ButtonGroupSeparator({ className, orientation = 'vertical', ...props }, ref) {
    return (
        <Separator
            ref={ref}
            data-slot="button-group-separator"
            orientation={orientation}
            className={cn('quill-button-group__separator', className)}
            {...props}
        />
    )
})

export { ButtonGroup, ButtonGroupSeparator, ButtonGroupText, buttonGroupVariants }
