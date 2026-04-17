import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { cn } from './lib/utils'
import { Separator } from './separator'

const buttonGroupVariants = cva(
    "flex w-fit items-stretch *:focus-visible:relative *:focus-visible:z-10 has-[>[data-slot=button-group]]:gap-2 has-[select[aria-hidden=true]:last-child]:[&>[data-slot=select-trigger]:last-of-type]:rounded-e-md [&>[data-slot=select-trigger]:not([class*='w-'])]:w-fit [&>input]:flex-1",
    {
        variants: {
            orientation: {
                horizontal:
                    '*:data-slot:rounded-e-none [&>[data-slot]:not(:has(~[data-slot]))]:rounded-e-md! [&>[data-slot]~[data-slot]]:rounded-s-none [&>[data-slot]~[data-slot]]:border-s-0',
                vertical:
                    'flex-col *:data-slot:rounded-b-none [&>[data-slot]:not(:has(~[data-slot]))]:rounded-b-md! [&>[data-slot]~[data-slot]]:rounded-t-none [&>[data-slot]~[data-slot]]:border-t-0',
            },
        },
        defaultVariants: {
            orientation: 'horizontal',
        },
    }
)

function ButtonGroup({
    className,
    orientation,
    ...props
}: React.ComponentProps<'div'> & VariantProps<typeof buttonGroupVariants>): React.ReactElement {
    return (
        <div
            role="group"
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
                className: cn(
                    "flex items-center gap-2 rounded-md text-xs/relaxed font-medium [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4",
                    className
                ),
            },
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
            className={cn(
                'relative self-stretch bg-border data-[orientation=horizontal]:mx-px data-[orientation=horizontal]:w-auto data-[orientation=vertical]:my-px data-[orientation=vertical]:h-auto',
                className
            )}
            {...props}
        />
    )
}

export { ButtonGroup, ButtonGroupSeparator, ButtonGroupText, buttonGroupVariants }
