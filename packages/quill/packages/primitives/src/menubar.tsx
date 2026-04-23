import { Menu as MenuPrimitive } from '@base-ui/react/menu'
import { Menubar as MenubarPrimitive } from '@base-ui/react/menubar'
import * as React from 'react'

import { Checkbox } from './checkbox'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuPortal,
    DropdownMenuRadioGroup,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from './dropdown-menu'
import { cn } from './lib/utils'
import { RadioIndicator } from './radio-group'

function Menubar({ className, ...props }: MenubarPrimitive.Props): React.ReactElement {
    return (
        <MenubarPrimitive
            data-slot="menubar"
            className={cn('flex h-9 items-center rounded-lg border bg-background p-1', className)}
            {...props}
        />
    )
}

function MenubarMenu({ ...props }: React.ComponentProps<typeof DropdownMenu>): React.ReactElement {
    return <DropdownMenu data-slot="menubar-menu" {...props} />
}

function MenubarGroup({ ...props }: React.ComponentProps<typeof DropdownMenuGroup>): React.ReactElement {
    return <DropdownMenuGroup data-slot="menubar-group" {...props} />
}

function MenubarPortal({ ...props }: React.ComponentProps<typeof DropdownMenuPortal>): React.ReactElement {
    return <DropdownMenuPortal data-slot="menubar-portal" {...props} />
}

function MenubarTrigger({ className, ...props }: React.ComponentProps<typeof DropdownMenuTrigger>): React.ReactElement {
    return (
        <DropdownMenuTrigger
            data-slot="menubar-trigger"
            className={cn(
                'flex items-center rounded-[calc(var(--radius-sm)-2px)] px-2 py-[calc(--spacing(0.85))] text-xs/relaxed font-medium outline-hidden select-none hover:bg-muted aria-expanded:bg-muted',
                className
            )}
            {...props}
        />
    )
}

function MenubarContent({
    className,
    align = 'start',
    alignOffset = -4,
    sideOffset = 8,
    ...props
}: React.ComponentProps<typeof DropdownMenuContent>): React.ReactElement {
    return (
        <DropdownMenuContent
            data-slot="menubar-content"
            align={align}
            alignOffset={alignOffset}
            sideOffset={sideOffset}
            className={cn(
                'min-w-32 rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 data-[side=bottom]:slide-in-from-top-2 data-[side=inline-end]:slide-in-from-start-2 data-[side=inline-start]:slide-in-from-end-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95',
                className
            )}
            {...props}
        />
    )
}

function MenubarItem({
    className,
    inset,
    variant = 'default',
    ...props
}: React.ComponentProps<typeof DropdownMenuItem>): React.ReactElement {
    return (
        <DropdownMenuItem
            data-slot="menubar-item"
            data-inset={inset}
            data-variant={variant}
            className={cn(
                "group/menubar-item min-h-7 gap-2 rounded-sm px-2 py-1 text-xs/relaxed focus:bg-accent focus:text-accent-foreground not-data-[variant=destructive]:focus:**:text-accent-foreground data-inset:ps-7.5 data-[variant=destructive]:text-destructive data-[variant=destructive]:focus:bg-destructive/10 data-[variant=destructive]:focus:text-destructive dark:data-[variant=destructive]:focus:bg-destructive/20 data-disabled:opacity-50 [&_svg:not([class*='size-'])]:size-3.5 data-[variant=destructive]:*:[svg]:text-destructive!",
                className
            )}
            {...props}
        />
    )
}

function MenubarCheckboxItem({
    className,
    children,
    checked,
    inset,
    ...props
}: MenuPrimitive.CheckboxItem.Props & {
    inset?: boolean
}): React.ReactElement {
    return (
        <MenuPrimitive.CheckboxItem
            data-slot="menubar-checkbox-item"
            data-inset={inset}
            className={cn(
                'relative flex min-h-7 cursor-default items-center gap-2 rounded-sm py-1.5 pe-2 ps-7.5 text-xs outline-hidden select-none focus:bg-accent focus:text-accent-foreground focus:**:text-accent-foreground data-inset:ps-7.5 data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0',
                className
            )}
            checked={checked}
            {...props}
        >
            <span className="pointer-events-none absolute start-2 flex size-4 items-center justify-center">
                <Checkbox size="sm" tabIndex={-1} />
                <MenuPrimitive.CheckboxItemIndicator className="absolute">
                    <Checkbox size="sm" checked tabIndex={-1} />
                </MenuPrimitive.CheckboxItemIndicator>
            </span>
            {children}
        </MenuPrimitive.CheckboxItem>
    )
}

function MenubarRadioGroup({ ...props }: React.ComponentProps<typeof DropdownMenuRadioGroup>): React.ReactElement {
    return <DropdownMenuRadioGroup data-slot="menubar-radio-group" {...props} />
}

function MenubarRadioItem({
    className,
    children,
    inset,
    ...props
}: MenuPrimitive.RadioItem.Props & {
    inset?: boolean
}): React.ReactElement {
    return (
        <MenuPrimitive.RadioItem
            data-slot="menubar-radio-item"
            data-inset={inset}
            className={cn(
                "relative flex min-h-7 cursor-default items-center gap-2 rounded-sm py-1.5 pe-2 ps-7.5 text-xs outline-hidden select-none focus:bg-accent focus:text-accent-foreground focus:**:text-accent-foreground data-inset:ps-7.5 data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            {...props}
        >
            <span className="pointer-events-none absolute start-2 flex size-4 items-center justify-center">
                <RadioIndicator size="sm" />
                <MenuPrimitive.RadioItemIndicator className="absolute">
                    <RadioIndicator size="sm" checked />
                </MenuPrimitive.RadioItemIndicator>
            </span>
            {children}
        </MenuPrimitive.RadioItem>
    )
}

function MenubarLabel({
    className,
    inset,
    ...props
}: React.ComponentProps<typeof DropdownMenuLabel> & {
    inset?: boolean
}): React.ReactElement {
    return (
        <DropdownMenuLabel
            data-slot="menubar-label"
            data-inset={inset}
            className={cn('px-2 py-1.5 text-xs text-muted-foreground data-inset:ps-7.5', className)}
            {...props}
        />
    )
}

function MenubarSeparator({
    className,
    ...props
}: React.ComponentProps<typeof DropdownMenuSeparator>): React.ReactElement {
    return (
        <DropdownMenuSeparator
            data-slot="menubar-separator"
            className={cn('-mx-1 my-1 h-px bg-border/50', className)}
            {...props}
        />
    )
}

function MenubarShortcut({
    className,
    ...props
}: React.ComponentProps<typeof DropdownMenuShortcut>): React.ReactElement {
    return (
        <DropdownMenuShortcut
            data-slot="menubar-shortcut"
            className={cn(
                'ms-auto text-[0.625rem] tracking-widest text-muted-foreground group-focus/menubar-item:text-accent-foreground',
                className
            )}
            {...props}
        />
    )
}

function MenubarSub({ ...props }: React.ComponentProps<typeof DropdownMenuSub>): React.ReactElement {
    return <DropdownMenuSub data-slot="menubar-sub" {...props} />
}

function MenubarSubTrigger({
    className,
    inset,
    ...props
}: React.ComponentProps<typeof DropdownMenuSubTrigger> & {
    inset?: boolean
}): React.ReactElement {
    return (
        <DropdownMenuSubTrigger
            data-slot="menubar-sub-trigger"
            data-inset={inset}
            className={cn(
                "min-h-7 gap-2 rounded-sm px-2 py-1 text-xs focus:bg-accent focus:text-accent-foreground not-data-[variant=destructive]:focus:**:text-accent-foreground data-inset:ps-7.5 data-open:bg-accent data-open:text-accent-foreground [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            {...props}
        />
    )
}

function MenubarSubContent({
    className,
    ...props
}: React.ComponentProps<typeof DropdownMenuSubContent>): React.ReactElement {
    return (
        <DropdownMenuSubContent
            data-slot="menubar-sub-content"
            className={cn(
                'min-w-32 rounded-lg bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95',
                className
            )}
            {...props}
        />
    )
}

export {
    Menubar,
    MenubarPortal,
    MenubarMenu,
    MenubarTrigger,
    MenubarContent,
    MenubarGroup,
    MenubarSeparator,
    MenubarLabel,
    MenubarItem,
    MenubarShortcut,
    MenubarCheckboxItem,
    MenubarRadioGroup,
    MenubarRadioItem,
    MenubarSub,
    MenubarSubTrigger,
    MenubarSubContent,
}
