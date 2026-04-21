import { ContextMenu as ContextMenuPrimitive } from '@base-ui/react/context-menu'
import { ChevronRightIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { Checkbox } from './checkbox'
import { cn } from './lib/utils'
import { RadioIndicator } from './radio-group'

function ContextMenu({ ...props }: ContextMenuPrimitive.Root.Props): React.ReactElement {
    return <ContextMenuPrimitive.Root data-slot="context-menu" {...props} />
}

function ContextMenuPortal({ ...props }: ContextMenuPrimitive.Portal.Props): React.ReactElement {
    return <ContextMenuPrimitive.Portal data-slot="context-menu-portal" {...props} />
}

function ContextMenuTrigger({ className, ...props }: ContextMenuPrimitive.Trigger.Props): React.ReactElement {
    return (
        <ContextMenuPrimitive.Trigger
            data-slot="context-menu-trigger"
            className={cn('select-none', className)}
            {...props}
        />
    )
}

function ContextMenuContent({
    className,
    align = 'start',
    alignOffset = 4,
    side = 'inline-end',
    sideOffset = 0,
    ...props
}: ContextMenuPrimitive.Popup.Props &
    Pick<ContextMenuPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset'>): React.ReactElement {
    return (
        <ContextMenuPrimitive.Portal>
            <ContextMenuPrimitive.Positioner
                className="isolate z-50 outline-none"
                align={align}
                alignOffset={alignOffset}
                side={side}
                sideOffset={sideOffset}
            >
                <ContextMenuPrimitive.Popup
                    data-slot="context-menu-content"
                    className={cn(
                        'z-50 max-h-(--available-height) min-w-32 origin-(--transform-origin) overflow-x-hidden overflow-y-auto rounded-md bg-popover p-1 text-popover-foreground shadow-md ring-1 ring-foreground/10 duration-100 outline-none data-[side=bottom]:slide-in-from-top-2 data-[side=inline-end]:slide-in-from-start-2 data-[side=inline-start]:slide-in-from-end-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95',
                        className
                    )}
                    {...props}
                />
            </ContextMenuPrimitive.Positioner>
        </ContextMenuPrimitive.Portal>
    )
}

function ContextMenuGroup({ ...props }: ContextMenuPrimitive.Group.Props): React.ReactElement {
    return <ContextMenuPrimitive.Group data-slot="context-menu-group" {...props} />
}

function ContextMenuLabel({
    className,
    inset,
    ...props
}: ContextMenuPrimitive.GroupLabel.Props & {
    inset?: boolean
}): React.ReactElement {
    return (
        <ContextMenuPrimitive.GroupLabel
            data-slot="context-menu-label"
            data-inset={inset}
            className={cn('px-2 py-1.5 text-xs text-muted-foreground data-inset:ps-7.5', className)}
            {...props}
        />
    )
}

function ContextMenuItem({
    className,
    inset,
    variant = 'default',
    children,
    ...props
}: ContextMenuPrimitive.Item.Props & {
    inset?: boolean
    variant?: 'default' | 'destructive'
}): React.ReactElement {
    return (
        <ContextMenuPrimitive.Item
            data-slot="context-menu-item"
            data-inset={inset}
            data-variant={variant}
            className={cn(
                "group/context-menu-item relative flex cursor-default items-center outline-hidden select-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            render={<Button variant={variant} className="w-full font-normal" left />}
            {...props}
        >
            {children}
        </ContextMenuPrimitive.Item>
    )
}

function ContextMenuSub({ ...props }: ContextMenuPrimitive.SubmenuRoot.Props): React.ReactElement {
    return <ContextMenuPrimitive.SubmenuRoot data-slot="context-menu-sub" {...props} />
}

function ContextMenuSubTrigger({
    className,
    inset,
    children,
    ...props
}: ContextMenuPrimitive.SubmenuTrigger.Props & {
    inset?: boolean
}): React.ReactElement {
    return (
        <ContextMenuPrimitive.SubmenuTrigger
            data-slot="context-menu-sub-trigger"
            data-inset={inset}
            className={cn(
                "flex cursor-default items-center outline-hidden select-none data-inset:ps-7.5 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            render={<Button className="w-full font-normal" left />}
            {...props}
        >
            {children}
            <ChevronRightIcon className="rtl:rotate-180 ms-auto" />
        </ContextMenuPrimitive.SubmenuTrigger>
    )
}

function ContextMenuSubContent({ ...props }: React.ComponentProps<typeof ContextMenuContent>): React.ReactElement {
    return (
        <ContextMenuContent
            data-slot="context-menu-sub-content"
            className="shadow-lg"
            side="inline-start"
            alignOffset={0}
            {...props}
        />
    )
}

function ContextMenuCheckboxItem({
    className,
    children,
    checked,
    inset,
    ...props
}: ContextMenuPrimitive.CheckboxItem.Props & {
    inset?: boolean
}): React.ReactElement {
    return (
        <ContextMenuPrimitive.CheckboxItem
            data-slot="context-menu-checkbox-item"
            data-inset={inset}
            className={cn(
                "relative flex cursor-default items-center ps-7.5 pe-2 text-xs outline-hidden select-none data-inset:ps-7.5 data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            render={<Button className="w-full font-normal" left />}
            checked={checked}
            {...props}
        >
            <span className="pointer-events-none absolute start-2 flex items-center justify-center">
                <Checkbox size="sm" tabIndex={-1} />
                <ContextMenuPrimitive.CheckboxItemIndicator className="absolute">
                    <Checkbox size="sm" checked tabIndex={-1} />
                </ContextMenuPrimitive.CheckboxItemIndicator>
            </span>
            {children}
        </ContextMenuPrimitive.CheckboxItem>
    )
}

function ContextMenuRadioGroup({ ...props }: ContextMenuPrimitive.RadioGroup.Props): React.ReactElement {
    return <ContextMenuPrimitive.RadioGroup data-slot="context-menu-radio-group" {...props} />
}

function ContextMenuRadioItem({
    className,
    children,
    inset,
    ...props
}: ContextMenuPrimitive.RadioItem.Props & {
    inset?: boolean
}): React.ReactElement {
    return (
        <ContextMenuPrimitive.RadioItem
            data-slot="context-menu-radio-item"
            data-inset={inset}
            className={cn(
                "relative flex cursor-default items-center ps-7.5 pe-2 outline-hidden select-none data-inset:ps-7.5 data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            render={<Button className="w-full font-normal" left />}
            {...props}
        >
            <span className="pointer-events-none absolute start-2 flex items-center justify-center">
                <RadioIndicator size="sm" />
                <ContextMenuPrimitive.RadioItemIndicator className="absolute">
                    <RadioIndicator size="sm" checked />
                </ContextMenuPrimitive.RadioItemIndicator>
            </span>
            {children}
        </ContextMenuPrimitive.RadioItem>
    )
}

function ContextMenuSeparator({ className, ...props }: ContextMenuPrimitive.Separator.Props): React.ReactElement {
    return (
        <ContextMenuPrimitive.Separator
            data-slot="context-menu-separator"
            className={cn('-mx-1 my-1 h-px bg-border/50', className)}
            {...props}
        />
    )
}

function ContextMenuShortcut({ className, ...props }: React.ComponentProps<'span'>): React.ReactElement {
    return (
        <span
            data-slot="context-menu-shortcut"
            className={cn(
                'ms-auto text-[0.625rem] tracking-widest text-muted-foreground group-focus/context-menu-item:text-accent-foreground',
                className
            )}
            {...props}
        />
    )
}

export {
    ContextMenu,
    ContextMenuTrigger,
    ContextMenuContent,
    ContextMenuItem,
    ContextMenuCheckboxItem,
    ContextMenuRadioItem,
    ContextMenuLabel,
    ContextMenuSeparator,
    ContextMenuShortcut,
    ContextMenuGroup,
    ContextMenuPortal,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    ContextMenuRadioGroup,
}
