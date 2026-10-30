import './item.css'

import { mergeProps } from '@base-ui/react/merge-props'
import { useRender } from '@base-ui/react/use-render'
import { cva, type VariantProps } from 'class-variance-authority'
import * as React from 'react'

import { CheckboxIndicator } from './checkbox'
import { cn } from './lib/utils'
import { RadioIndicator } from './radio-group'
import { Separator } from './separator'

const ItemGroup = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'> & { combined?: boolean }>(
    function ItemGroup({ className, combined = false, ...props }, ref) {
        return (
            <div
                ref={ref}
                role="list"
                data-slot="item-group"
                data-combined={combined ? '' : undefined}
                className={cn(
                    'quill-item-group group/item-group flex w-full flex-col',
                    combined ? 'gap-0' : 'gap-4 has-data-[size=sm]:gap-2.5 has-data-[size=xs]:gap-2',
                    className
                )}
                {...props}
            />
        )
    }
)

const ItemSeparator = React.forwardRef<React.ComponentRef<typeof Separator>, React.ComponentProps<typeof Separator>>(
    function ItemSeparator({ className, ...props }, ref) {
        return (
            <Separator
                ref={ref}
                data-slot="item-separator"
                orientation="horizontal"
                className={cn('my-2', className)}
                {...props}
            />
        )
    }
)

const itemVariants = cva('quill-item item group/item flex w-full flex-wrap items-center', {
    variants: {
        variant: {
            default: 'quill-item--variant-default',
            outline: 'quill-item--variant-outline',
            muted: 'quill-item--variant-muted',
            menuItem: 'quill-item--variant-menu',
        },
        size: {
            default: 'quill-item--size-default',
            sm: 'quill-item--size-sm',
            xs: 'quill-item--size-xs',
        },
        tone: {
            default: '',
            info: 'quill-item--tone-info',
            success: 'quill-item--tone-success',
            warning: 'quill-item--tone-warning',
            completed: 'quill-item--tone-completed',
            destructive: 'quill-item--tone-destructive',
        },
    },
    defaultVariants: {
        variant: 'default',
        size: 'default',
        tone: 'default',
    },
})

const Item = React.forwardRef<HTMLDivElement, useRender.ComponentProps<'div'> & VariantProps<typeof itemVariants>>(
    function Item({ className, variant = 'default', size = 'default', tone = 'default', render, ...props }, ref) {
        return useRender({
            ref,
            defaultTagName: 'div',
            props: mergeProps<'div'>(
                {
                    'data-quill': '',
                    'data-tone': tone && tone !== 'default' ? tone : undefined,
                    className: cn(itemVariants({ variant, size, tone, className })),
                } as Omit<React.ComponentProps<'div'>, 'ref'>,
                props
            ),
            render,
            state: {
                slot: 'item',
                variant,
                size,
                tone,
            },
        })
    }
)

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
            } as Omit<React.ComponentProps<'button'>, 'ref'>,
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
            } as Omit<React.ComponentProps<'button'>, 'ref'>,
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
            <CheckboxIndicator checked={checked} size="sm" />
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
            } as Omit<React.ComponentProps<'button'>, 'ref'>,
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
            <RadioIndicator checked={checked} size="sm" />
        </ItemMedia>,
        children
    )
})

const itemMediaVariants = cva('quill-item__media flex shrink-0 items-center justify-center gap-2', {
    variants: {
        variant: {
            default: 'quill-item__media--variant-default',
            icon: 'quill-item__media--variant-icon',
            image: 'quill-item__media--variant-image',
            checkbox: 'quill-item__media--variant-checkbox',
        },
    },
    defaultVariants: {
        variant: 'default',
    },
})

const ItemMedia = React.forwardRef<
    HTMLDivElement,
    React.ComponentProps<'div'> & VariantProps<typeof itemMediaVariants>
>(function ItemMedia({ className, variant = 'default', ...props }, ref) {
    return (
        <div
            ref={ref}
            data-slot="item-media"
            data-variant={variant}
            className={cn(itemMediaVariants({ variant, className }))}
            {...props}
        />
    )
})

const itemContentVariants = cva('quill-item__content flex flex-1 flex-col gap-1', {
    variants: {
        variant: {
            default: '',
            menuItem: 'quill-item__content--variant-menu',
        },
    },
    defaultVariants: {
        variant: 'default',
    },
})

const ItemContent = React.forwardRef<
    HTMLDivElement,
    React.ComponentProps<'div'> & VariantProps<typeof itemContentVariants>
>(function ItemContent({ className, variant = 'default', ...props }, ref) {
    return (
        <div
            ref={ref}
            data-slot="item-content"
            className={cn(itemContentVariants({ variant, className }))}
            {...props}
        />
    )
})

const ItemTitle = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ItemTitle(
    { className, ...props },
    ref
) {
    return <div ref={ref} data-slot="item-title" className={cn('quill-item__title gap-2', className)} {...props} />
})

const ItemDescription = React.forwardRef<HTMLParagraphElement, React.ComponentProps<'p'>>(function ItemDescription(
    { className, ...props },
    ref
) {
    return <p ref={ref} data-slot="item-description" className={cn('quill-item__description', className)} {...props} />
})

const ItemActions = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ItemActions(
    { className, ...props },
    ref
) {
    return <div ref={ref} data-slot="item-actions" className={cn('flex items-center gap-2', className)} {...props} />
})

const ItemHeader = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ItemHeader(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="item-header"
            className={cn('flex basis-full items-center justify-between gap-2', className)}
            {...props}
        />
    )
})

const ItemFooter = React.forwardRef<HTMLDivElement, React.ComponentProps<'div'>>(function ItemFooter(
    { className, ...props },
    ref
) {
    return (
        <div
            ref={ref}
            data-slot="item-footer"
            className={cn('flex basis-full items-center justify-between gap-2', className)}
            {...props}
        />
    )
})

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
