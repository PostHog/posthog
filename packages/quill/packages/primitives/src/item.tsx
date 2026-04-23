import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { CheckboxIndicator } from './checkbox'
import { cn } from './lib/utils'
import { RadioIndicator } from './radio-group'
import { Separator } from './separator'

function ItemGroup({
    className,
    combined = false,
    ...props
}: React.ComponentProps<'div'> & { combined?: boolean }): React.ReactElement {
    return (
        <div
            role="list"
            data-slot="item-group"
            data-combined={combined || undefined}
            className={cn(
                'group/item-group flex w-full flex-col gap-4 has-data-[size=sm]:gap-2.5 has-data-[size=xs]:gap-2',
                combined && 'gap-0 has-data-[size=sm]:gap-0 has-data-[size=xs]:gap-0',
                className
            )}
            {...props}
        />
    )
}

function ItemSeparator({ className, ...props }: React.ComponentProps<typeof Separator>): React.ReactElement {
    return (
        <Separator data-slot="item-separator" orientation="horizontal" className={cn('my-2', className)} {...props} />
    )
}

const itemVariants = cva(
    'item group/item flex w-full flex-wrap items-center rounded-sm border text-xs/relaxed transition-colors duration-100 outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30 in-data-[combined]:rounded-none in-data-[combined]:first:rounded-t-sm in-data-[combined]:last:rounded-b-sm in-data-[combined]:not-last:border-b-0 focus-visible:z-1 -outline-offset-2 in-data-[slot=combobox-item]:border-none',
    {
        variants: {
            variant: {
                default: 'border-card',
                outline: 'border-border',
                pressable:
                    'transition-colors hover:border-secondary/20 hover:shadow hover:z-1 hover:group-data-[combined=true]/item-group:shadow-none hover:group-data-[combined=true]/item-group:border-border',
                muted: 'border-transparent bg-muted/50',
                menuItem: 'hover:bg-fill-hover hover:text-foreground border-none',
            },
            size: {
                default: 'gap-2.5 px-3 py-2.5',
                sm: 'gap-2.5 px-3 py-2.5',
                xs: 'gap-2.5 px-2.5 py-2 in-data-[slot=dropdown-menu-content]:p-0',
            },
        },
        defaultVariants: {
            variant: 'default',
            size: 'default',
        },
    }
)

function Item({
    className,
    variant = 'default',
    size = 'default',
    role,
    render,
    ...props
}: useRender.ComponentProps<'div'> & VariantProps<typeof itemVariants>): React.ReactElement {
    return useRender({
        defaultTagName: 'div',
        props: mergeProps<'div'>(
            {
                'data-quill': '',
                className: cn(itemVariants({ variant, size, className })),
                role: variant === 'pressable' ? 'link' : undefined,
            },
            props
        ),
        render,
        state: {
            slot: 'item',
            variant,
            size,
        },
    })
}

const ItemMenuItem = React.forwardRef<
    HTMLButtonElement,
    useRender.ComponentProps<'button'> & VariantProps<typeof itemVariants>
>(function ItemMenuItem({ className, variant = 'default', size = 'default', render, ...props }, ref) {
    return useRender({
        defaultTagName: 'button',
        props: mergeProps<'button'>(
            {
                className: cn(itemVariants({ variant: 'menuItem', size, className })),
                role: 'menuitem',
                ref,
            },
            props
        ),
        render,
        state: {
            slot: 'item',
            variant,
            size,
        },
    })
})

const ItemCheckbox = React.forwardRef<
    HTMLButtonElement,
    useRender.ComponentProps<'button'> & VariantProps<typeof itemVariants>
>(function ItemCheckbox({ className, variant = 'default', size = 'default', render, children, ...props }, ref) {
    const checked = props['aria-checked'] === true || props['aria-checked'] === 'true'
    const element = useRender({
        defaultTagName: 'button',
        props: mergeProps<'button'>(
            {
                className: cn(itemVariants({ variant: 'menuItem', size, className })),
                role: 'checkbox',
                ref,
            },
            props
        ),
        render,
        state: {
            slot: 'item',
            variant,
            size,
        },
    })
    return React.cloneElement(
        element,
        {},
        <ItemMedia variant="checkbox" className="-mr-2">
            <CheckboxIndicator checked={checked} size="sm"/>
        </ItemMedia>,
        children
    )
})

const ItemRadio = React.forwardRef<
    HTMLButtonElement,
    useRender.ComponentProps<'button'> & VariantProps<typeof itemVariants>
>(function ItemRadio({ className, variant = 'default', size = 'default', render, children, ...props }, ref) {
    const checked = props['aria-checked'] === true || props['aria-checked'] === 'true'
    const element = useRender({
        defaultTagName: 'button',
        props: mergeProps<'button'>(
            {
                className: cn(itemVariants({ variant: 'menuItem', size, className })),
                role: 'radio',
                ref,
            },
            props
        ),
        render,
        state: {
            slot: 'item',
            variant,
            size,
        },
    })
    return React.cloneElement(
        element,
        {},
        <ItemMedia variant="checkbox" className="-mr-2">
            <RadioIndicator checked={checked} size="sm"/>
        </ItemMedia>,
        children
    )
})

const itemMediaVariants = cva(
    'flex shrink-0 items-center justify-center gap-2 group-has-data-[slot=item-description]/item:translate-y-0.5 group-has-data-[slot=item-description]/item:self-start [&_svg]:pointer-events-none',
    {
        variants: {
            variant: {
                default: 'bg-transparent',
                icon: "[&_svg:not([class*='size-'])]:size-4",
                image: 'size-8 overflow-hidden rounded-sm group-data-[size=sm]/item:size-8 group-data-[size=xs]/item:size-6 [&_img]:size-full [&_img]:object-cover',
                checkbox:
                    'size-8 overflow-hidden rounded-sm group-data-[size=sm]/item:size-8 group-data-[size=xs]/item:size-6 [&_img]:size-full [&_img]:object-cover',
            },
        },
        defaultVariants: {
            variant: 'default',
        },
    }
)

function ItemMedia({
    className,
    variant = 'default',
    ...props
}: React.ComponentProps<'div'> & VariantProps<typeof itemMediaVariants>): React.ReactElement {
    return (
        <div
            data-slot="item-media"
            data-variant={variant}
            className={cn(itemMediaVariants({ variant, className }), 'group-[&[role=link]:hover]/item:text-primary')}
            {...props}
        />
    )
}

const itemContentVariants = cva(
    'flex flex-1 flex-col gap-1 group-data-[size=xs]/item:gap-0.5 [&+[data-slot=item-content]]:flex-none',
    {
        variants: {
            variant: {
                default: '',
                menuItem: `
                    w-full py-1 px-1.5 
                    group-data-[slot=combobox-item]/button:px-0 
                    group-data-[slot=select-trigger]/button:px-0 
                    group-data-[slot=select-item]/select-item:px-0 
                    group-has-data-[slot=item-media]/item:pl-0
                `,
            },
        },
        defaultVariants: {
            variant: 'default',
        },
    }
)

function ItemContent({
    className,
    variant = 'default',
    ...props
}: React.ComponentProps<'div'> & VariantProps<typeof itemContentVariants>): React.ReactElement {
    return (
        <div
            data-slot="item-content"
            className={cn(itemContentVariants({ variant, className }), className)}
            {...props}
        />
    )
}

function ItemTitle({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="item-title"
            className={cn(
                'line-clamp-1 flex w-fit items-center gap-2 text-xs/relaxed leading-snug font-medium underline-offset-4',
                'group-[&[role=link]:hover]/item:text-primary',
                className
            )}
            {...props}
        />
    )
}

function ItemDescription({ className, ...props }: React.ComponentProps<'p'>): React.ReactElement {
    return (
        <p
            data-slot="item-description"
            className={cn(
                'line-clamp-2 text-start text-xxs font-normal text-muted-foreground [&>a]:underline [&>a]:underline-offset-4 [&>a:hover]:text-primary',
                className
            )}
            {...props}
        />
    )
}

function ItemActions({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return <div data-slot="item-actions" className={cn('flex items-center gap-2', className)} {...props} />
}

function ItemHeader({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="item-header"
            className={cn('flex basis-full items-center justify-between gap-2', className)}
            {...props}
        />
    )
}

function ItemFooter({ className, ...props }: React.ComponentProps<'div'>): React.ReactElement {
    return (
        <div
            data-slot="item-footer"
            className={cn('flex basis-full items-center justify-between gap-2', className)}
            {...props}
        />
    )
}

export {
    Item,
    ItemCheckbox,
    ItemRadio,
    ItemMenuItem,
    ItemMedia,
    ItemContent,
    ItemActions,
    ItemGroup,
    ItemSeparator,
    ItemTitle,
    ItemDescription,
    ItemHeader,
    ItemFooter,
}
