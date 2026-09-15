import './menu.css'

import { Menubar as MenubarPrimitive } from '@base-ui/react/menubar'
import * as React from 'react'

import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuPortal,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from './dropdown-menu'
import { cn } from './lib/utils'

function Menubar({ className, ...props }: MenubarPrimitive.Props): React.ReactElement {
    return (
        <MenubarPrimitive
            data-quill
            data-slot="menubar"
            className={cn('quill-menubar flex items-center', className)}
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
            className={cn('quill-menubar__trigger flex items-center outline-hidden select-none', className)}
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
            className={className}
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
            variant={variant}
            className={cn(
                'group/menubar-item min-h-7 gap-2 rounded-sm px-2 py-1 data-disabled:opacity-50',
                className
            )}
            {...props}
        />
    )
}

function MenubarCheckboxItem({ ...props }: React.ComponentProps<typeof DropdownMenuCheckboxItem>): React.ReactElement {
    return <DropdownMenuCheckboxItem data-slot="menubar-checkbox-item" {...props} />
}

function MenubarRadioGroup({ ...props }: React.ComponentProps<typeof DropdownMenuRadioGroup>): React.ReactElement {
    return <DropdownMenuRadioGroup data-slot="menubar-radio-group" {...props} />
}

function MenubarRadioItem({ ...props }: React.ComponentProps<typeof DropdownMenuRadioItem>): React.ReactElement {
    return <DropdownMenuRadioItem data-slot="menubar-radio-item" {...props} />
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
            className={cn('px-2 py-1.5 text-xs text-muted-foreground', inset && 'quill-menu-item--inset', className)}
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
            className={cn('quill-menu__separator', className)}
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
            className={cn('quill-menu__shortcut', className)}
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
                "min-h-7 gap-2 rounded-sm px-2 py-1 focus:bg-fill-hover data-open:bg-fill-selected [&_svg:not([class*='size-'])]:size-3.5",
                inset && 'quill-menu-item--inset',
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
    return <DropdownMenuSubContent data-slot="menubar-sub-content" className={className} {...props} />
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
