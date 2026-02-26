'use client'

import * as ContextMenuPrimitive from '@radix-ui/react-context-menu'
import * as React from 'react'

import { IconCheckCircle } from '@posthog/icons'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { cn } from 'lib/utils/css-classes'

import { MenuSeparator } from '../Menus/Menus'

const ContextMenu = ContextMenuPrimitive.Root

const ContextMenuTrigger = ContextMenuPrimitive.Trigger

const ContextMenuGroup = ({
    ref,
    className,
    ...props
}: React.ComponentProps<typeof ContextMenuPrimitive.Group>): JSX.Element => {
    return <ContextMenuPrimitive.Group ref={ref} className={cn('flex flex-col gap-px p-1', className)} {...props} />
}
ContextMenuGroup.displayName = ContextMenuPrimitive.Group.displayName

const ContextMenuPortal = ContextMenuPrimitive.Portal

const ContextMenuSub = ContextMenuPrimitive.Sub

const ContextMenuRadioGroup = ContextMenuPrimitive.RadioGroup

interface ContextMenuSubTriggerProps extends React.ComponentProps<typeof ContextMenuPrimitive.SubTrigger> {
    inset?: boolean
}

const ContextMenuSubTrigger = ({ ref, className, inset, ...props }: ContextMenuSubTriggerProps): JSX.Element => (
    <ContextMenuPrimitive.SubTrigger ref={ref} className={cn(inset && 'pl-7', className)} {...props} />
)
ContextMenuSubTrigger.displayName = ContextMenuPrimitive.SubTrigger.displayName

const ContextMenuSubContent = ({
    ref,
    className,
    collisionPadding = { top: 50, bottom: 50 },
    children,
    ...props
}: React.ComponentProps<typeof ContextMenuPrimitive.SubContent>): JSX.Element => (
    <ContextMenuPrimitive.SubContent
        ref={ref}
        collisionPadding={collisionPadding}
        className={cn('primitive-menu-content max-h-[var(--radix-context-menu-content-available-height)]', className)}
        {...props}
    >
        <ScrollableShadows direction="vertical" styledScrollbars innerClassName="primitive-menu-content-inner">
            {children}
        </ScrollableShadows>
    </ContextMenuPrimitive.SubContent>
)
ContextMenuSubContent.displayName = ContextMenuPrimitive.SubContent.displayName

const ContextMenuContent = ({
    ref,
    className,
    children,
    collisionPadding = { top: 50, bottom: 50 },
    ...props
}: React.ComponentProps<typeof ContextMenuPrimitive.Content>): JSX.Element => (
    <ContextMenuPrimitive.Portal>
        <ContextMenuPrimitive.Content
            ref={ref}
            collisionPadding={collisionPadding}
            className={cn(
                `primitive-menu-content max-h-[var(--radix-context-menu-content-available-height)]`,
                className
            )}
            {...props}
        >
            <ScrollableShadows direction="vertical" styledScrollbars innerClassName="primitive-menu-content-inner">
                {children}
            </ScrollableShadows>
        </ContextMenuPrimitive.Content>
    </ContextMenuPrimitive.Portal>
)
ContextMenuContent.displayName = ContextMenuPrimitive.Content.displayName

interface ContextMenuItemProps extends React.ComponentProps<typeof ContextMenuPrimitive.Item> {
    inset?: boolean
}

const ContextMenuItem = ({ ref, className, inset, ...props }: ContextMenuItemProps): JSX.Element => (
    <ContextMenuPrimitive.Item ref={ref} className={cn(inset && 'pl-7', className)} {...props} />
)
ContextMenuItem.displayName = ContextMenuPrimitive.Item.displayName

const ContextMenuCheckboxItem = ({
    ref,
    className,
    children,
    checked,
    ...props
}: React.ComponentProps<typeof ContextMenuPrimitive.CheckboxItem>): JSX.Element => (
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
ContextMenuCheckboxItem.displayName = ContextMenuPrimitive.CheckboxItem.displayName

const ContextMenuRadioItem = ({
    ref,
    className,
    children,
    ...props
}: React.ComponentProps<typeof ContextMenuPrimitive.RadioItem>): JSX.Element => (
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
ContextMenuRadioItem.displayName = ContextMenuPrimitive.RadioItem.displayName

interface ContextMenuLabelProps extends React.ComponentProps<typeof ContextMenuPrimitive.Label> {
    inset?: boolean
}

const ContextMenuLabel = ({ ref, className, inset, ...props }: ContextMenuLabelProps): JSX.Element => (
    <ContextMenuPrimitive.Label
        ref={ref}
        className={cn('px-2 py-1.5 text-sm font-semibold text-foreground', inset && 'pl-7', className)}
        {...props}
    />
)
ContextMenuLabel.displayName = ContextMenuPrimitive.Label.displayName

const ContextMenuSeparator = ({
    ref,
    className,
    ...props
}: React.ComponentProps<typeof ContextMenuPrimitive.Separator>): JSX.Element => (
    <ContextMenuPrimitive.Separator ref={ref} asChild {...props}>
        <MenuSeparator className={className} />
    </ContextMenuPrimitive.Separator>
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
