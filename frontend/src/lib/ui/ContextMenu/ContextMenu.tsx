'use client'

import { IconCheckCircle } from '@posthog/icons'
import * as ContextMenuPrimitive from '@radix-ui/react-context-menu'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'
import * as React from 'react'

const ContextMenu = ContextMenuPrimitive.Root

const ContextMenuTrigger = ContextMenuPrimitive.Trigger

const ContextMenuGroup = React.forwardRef<
    React.ElementRef<typeof ContextMenuPrimitive.Group>,
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Group>
>(({ className, ...props }, ref): JSX.Element => {
    return <ContextMenuPrimitive.Group ref={ref} className={cn('flex flex-col gap-px', className)} {...props} />
})
ContextMenuGroup.displayName = ContextMenuPrimitive.Group.displayName

const ContextMenuPortal = ContextMenuPrimitive.Portal

const ContextMenuSub = ContextMenuPrimitive.Sub

const ContextMenuRadioGroup = ContextMenuPrimitive.RadioGroup

const ContextMenuSubTrigger = React.forwardRef<
    React.ElementRef<typeof ContextMenuPrimitive.SubTrigger>,
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.SubTrigger> & {
        inset?: boolean
    }
>(
    ({ className, inset, ...props }, ref): JSX.Element => (
        <ContextMenuPrimitive.SubTrigger ref={ref} className={cn(inset && 'pl-7', className)} {...props} />
    )
)
ContextMenuSubTrigger.displayName = ContextMenuPrimitive.SubTrigger.displayName

const ContextMenuSubContent = React.forwardRef<
    React.ElementRef<typeof ContextMenuPrimitive.SubContent>,
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.SubContent>
>(
    ({ className, collisionPadding = { top: 50, bottom: 50 }, children, ...props }, ref): JSX.Element => (
        <ContextMenuPrimitive.SubContent
            ref={ref}
            collisionPadding={collisionPadding}
            className={cn('primitive-menu-content', className)}
            {...props}
        >
            <ScrollableShadows direction="vertical" styledScrollbars innerClassName="primitive-menu-content-inner">
                {children}
            </ScrollableShadows>
        </ContextMenuPrimitive.SubContent>
    )
)
ContextMenuSubContent.displayName = ContextMenuPrimitive.SubContent.displayName

const ContextMenuContent = React.forwardRef<
    React.ElementRef<typeof ContextMenuPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Content>
>(
    ({ className, children, collisionPadding = { top: 50, bottom: 50 }, ...props }, ref): JSX.Element => (
        <ContextMenuPrimitive.Portal>
            <ContextMenuPrimitive.Content
                ref={ref}
                collisionPadding={collisionPadding}
                className={cn(`primitive-menu-content`, className)}
                {...props}
            >
                <ScrollableShadows direction="vertical" styledScrollbars innerClassName="primitive-menu-content-inner">
                    {children}
                </ScrollableShadows>
            </ContextMenuPrimitive.Content>
        </ContextMenuPrimitive.Portal>
    )
)
ContextMenuContent.displayName = ContextMenuPrimitive.Content.displayName

const ContextMenuItem = React.forwardRef<
    React.ElementRef<typeof ContextMenuPrimitive.Item>,
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Item> & {
        inset?: boolean
    }
>(
    ({ className, inset, ...props }, ref): JSX.Element => (
        <ContextMenuPrimitive.Item ref={ref} className={cn(inset && 'pl-7', className)} {...props} />
    )
)
ContextMenuItem.displayName = ContextMenuPrimitive.Item.displayName

const ContextMenuCheckboxItem = React.forwardRef<
    React.ElementRef<typeof ContextMenuPrimitive.CheckboxItem>,
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.CheckboxItem>
>(
    ({ className, children, checked, ...props }, ref): JSX.Element => (
        <ContextMenuPrimitive.CheckboxItem
            ref={ref}
            className={cn(
                'relative flex cursor-default select-none items-center rounded-xs py-1.5 pl-8 pr-2 text-sm outline-hidden focus:bg-accent-highlight focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
                className
            )}
            checked={checked}
            {...props}
        >
            <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
                <ContextMenuPrimitive.ItemIndicator>
                    <IconCheckCircle className="h-4 w-4" />
                </ContextMenuPrimitive.ItemIndicator>
            </span>
            {children}
        </ContextMenuPrimitive.CheckboxItem>
    )
)
ContextMenuCheckboxItem.displayName = ContextMenuPrimitive.CheckboxItem.displayName

const ContextMenuRadioItem = React.forwardRef<
    React.ElementRef<typeof ContextMenuPrimitive.RadioItem>,
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.RadioItem>
>(
    ({ className, children, ...props }, ref): JSX.Element => (
        <ContextMenuPrimitive.RadioItem
            ref={ref}
            className={cn(
                'relative flex cursor-default select-none items-center rounded-xs py-1.5 pl-8 pr-2 text-sm outline-hidden focus:bg-accent-highlight focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
                className
            )}
            {...props}
        >
            <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
                <ContextMenuPrimitive.ItemIndicator>
                    <div className="h-4 w-4 fill-current aspect-square" />
                </ContextMenuPrimitive.ItemIndicator>
            </span>
            {children}
        </ContextMenuPrimitive.RadioItem>
    )
)
ContextMenuRadioItem.displayName = ContextMenuPrimitive.RadioItem.displayName

const ContextMenuLabel = React.forwardRef<
    React.ElementRef<typeof ContextMenuPrimitive.Label>,
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Label> & {
        inset?: boolean
    }
>(
    ({ className, inset, ...props }, ref): JSX.Element => (
        <ContextMenuPrimitive.Label
            ref={ref}
            className={cn('px-2 py-1.5 text-sm font-semibold text-foreground', inset && 'pl-7', className)}
            {...props}
        />
    )
)
ContextMenuLabel.displayName = ContextMenuPrimitive.Label.displayName

const ContextMenuSeparator = React.forwardRef<
    React.ElementRef<typeof ContextMenuPrimitive.Separator>,
    React.ComponentPropsWithoutRef<typeof ContextMenuPrimitive.Separator>
>(
    ({ className, ...props }, ref): JSX.Element => (
        <ContextMenuPrimitive.Separator
            ref={ref}
            className={cn('-mx-1 my-1 h-px bg-border-primary', className)}
            {...props}
        />
    )
)
ContextMenuSeparator.displayName = ContextMenuPrimitive.Separator.displayName

const ContextMenuShortcut = ({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>): JSX.Element => {
    return <span className={cn('ml-auto text-xs tracking-widest text-muted-foreground', className)} {...props} />
}
ContextMenuShortcut.displayName = 'ContextMenuShortcut'

export {
    ContextMenu,
    ContextMenuCheckboxItem,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuLabel,
    ContextMenuPortal,
    ContextMenuRadioGroup,
    ContextMenuRadioItem,
    ContextMenuSeparator,
    ContextMenuShortcut,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    ContextMenuTrigger,
}
