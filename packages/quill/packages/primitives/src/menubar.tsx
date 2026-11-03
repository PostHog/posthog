import './menu.css'

import type { Menu as MenuPrimitive } from '@base-ui/react/menu'
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

const Menubar = React.forwardRef<React.ComponentRef<typeof MenubarPrimitive>, MenubarPrimitive.Props>(function Menubar(
    { className, ...props },
    ref
) {
    return (
        <MenubarPrimitive
            ref={ref}
            data-quill
            data-slot="menubar"
            className={cn('quill-menubar flex items-center', className)}
            {...props}
        />
    )
})

function MenubarMenu({ ...props }: React.ComponentProps<typeof DropdownMenu>): React.ReactElement {
    return <DropdownMenu data-slot="menubar-menu" {...props} />
}

const MenubarGroup = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuGroup>,
    React.ComponentProps<typeof DropdownMenuGroup>
>(function MenubarGroup({ ...props }, ref) {
    return <DropdownMenuGroup ref={ref} data-slot="menubar-group" {...props} />
})

function MenubarPortal({ ...props }: React.ComponentProps<typeof DropdownMenuPortal>): React.ReactElement {
    return <DropdownMenuPortal data-slot="menubar-portal" {...props} />
}

const MenubarTrigger = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuTrigger>,
    React.ComponentProps<typeof DropdownMenuTrigger>
>(function MenubarTrigger({ className, ...props }, ref) {
    return (
        <DropdownMenuTrigger
            ref={ref}
            data-slot="menubar-trigger"
            className={cn('quill-menubar__trigger flex items-center outline-hidden select-none', className)}
            {...props}
        />
    )
})

const MenubarContent = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuContent>,
    React.ComponentProps<typeof DropdownMenuContent>
>(function MenubarContent({ className, align = 'start', alignOffset = -4, sideOffset = 8, ...props }, ref) {
    return (
        <DropdownMenuContent
            ref={ref}
            data-slot="menubar-content"
            align={align}
            alignOffset={alignOffset}
            sideOffset={sideOffset}
            className={className}
            {...props}
        />
    )
})

const MenubarItem = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuItem>,
    React.ComponentProps<typeof DropdownMenuItem>
>(function MenubarItem({ className, inset, variant = 'default', ...props }, ref) {
    return (
        <DropdownMenuItem
            ref={ref}
            data-slot="menubar-item"
            data-inset={inset}
            variant={variant}
            className={cn('group/menubar-item min-h-7 gap-2 rounded-sm px-2 py-1 data-disabled:opacity-50', className)}
            {...props}
        />
    )
})

// Explicit Base UI props, not `ComponentProps<typeof ...>`, so inline `onCheckedChange` callbacks keep their parameter type.
const MenubarCheckboxItem = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuCheckboxItem>,
    MenuPrimitive.CheckboxItem.Props & { inset?: boolean }
>(function MenubarCheckboxItem({ ...props }, ref) {
    return <DropdownMenuCheckboxItem ref={ref} data-slot="menubar-checkbox-item" {...props} />
})

const MenubarRadioGroup = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuRadioGroup>,
    React.ComponentProps<typeof DropdownMenuRadioGroup>
>(function MenubarRadioGroup({ ...props }, ref) {
    return <DropdownMenuRadioGroup ref={ref} data-slot="menubar-radio-group" {...props} />
})

const MenubarRadioItem = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuRadioItem>,
    MenuPrimitive.RadioItem.Props & { inset?: boolean }
>(function MenubarRadioItem({ ...props }, ref) {
    return <DropdownMenuRadioItem ref={ref} data-slot="menubar-radio-item" {...props} />
})

const MenubarLabel = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuLabel>,
    React.ComponentProps<typeof DropdownMenuLabel> & {
        inset?: boolean
    }
>(function MenubarLabel({ className, inset, ...props }, ref) {
    return (
        <DropdownMenuLabel
            ref={ref}
            data-slot="menubar-label"
            data-inset={inset}
            className={cn('px-2 py-1.5 text-xs text-muted-foreground', inset && 'quill-menu-item--inset', className)}
            {...props}
        />
    )
})

const MenubarSeparator = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuSeparator>,
    React.ComponentProps<typeof DropdownMenuSeparator>
>(function MenubarSeparator({ className, ...props }, ref) {
    return (
        <DropdownMenuSeparator
            ref={ref}
            data-slot="menubar-separator"
            className={cn('quill-menu__separator', className)}
            {...props}
        />
    )
})

const MenubarShortcut = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuShortcut>,
    React.ComponentProps<typeof DropdownMenuShortcut>
>(function MenubarShortcut({ className, ...props }, ref) {
    return (
        <DropdownMenuShortcut
            ref={ref}
            data-slot="menubar-shortcut"
            className={cn('quill-menu__shortcut', className)}
            {...props}
        />
    )
})

function MenubarSub({ ...props }: React.ComponentProps<typeof DropdownMenuSub>): React.ReactElement {
    return <DropdownMenuSub data-slot="menubar-sub" {...props} />
}

const MenubarSubTrigger = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuSubTrigger>,
    React.ComponentProps<typeof DropdownMenuSubTrigger> & {
        inset?: boolean
    }
>(function MenubarSubTrigger({ className, inset, ...props }, ref) {
    return (
        <DropdownMenuSubTrigger
            ref={ref}
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
})

const MenubarSubContent = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuSubContent>,
    React.ComponentProps<typeof DropdownMenuSubContent>
>(function MenubarSubContent({ className, ...props }, ref) {
    return <DropdownMenuSubContent ref={ref} data-slot="menubar-sub-content" className={className} {...props} />
})

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
