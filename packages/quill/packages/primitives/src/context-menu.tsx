import './menu.css'

import { ContextMenu as ContextMenuPrimitive } from '@base-ui/react/context-menu'
import { ChevronRightIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { Checkbox } from './checkbox'
import { Kbd } from './kbd'
import { cn } from './lib/utils'
import { RadioIndicator } from './radio-group'

function ContextMenu({ ...props }: ContextMenuPrimitive.Root.Props): React.ReactElement {
    return <ContextMenuPrimitive.Root data-slot="context-menu" {...props} />
}

function ContextMenuPortal({ ...props }: ContextMenuPrimitive.Portal.Props): React.ReactElement {
    return <ContextMenuPrimitive.Portal data-slot="context-menu-portal" {...props} />
}

const ContextMenuTrigger = React.forwardRef<
    React.ComponentRef<typeof ContextMenuPrimitive.Trigger>,
    ContextMenuPrimitive.Trigger.Props
>(function ContextMenuTrigger({ className, ...props }, ref) {
    return (
        <ContextMenuPrimitive.Trigger
            ref={ref}
            data-slot="context-menu-trigger"
            className={cn('select-none', className)}
            {...props}
        />
    )
})

const ContextMenuContent = React.forwardRef<
    React.ComponentRef<typeof ContextMenuPrimitive.Popup>,
    ContextMenuPrimitive.Popup.Props &
        Pick<ContextMenuPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset'>
>(function ContextMenuContent(
    { className, align = 'start', alignOffset = 4, side = 'inline-end', sideOffset = 0, children, ...props },
    ref
) {
    return (
        <ContextMenuPrimitive.Portal>
            <ContextMenuPrimitive.Positioner
                data-quill
                data-quill-portal="popover"
                className="isolate outline-none"
                align={align}
                alignOffset={alignOffset}
                side={side}
                sideOffset={sideOffset}
            >
                <ContextMenuPrimitive.Popup
                    ref={ref}
                    data-slot="context-menu-content"
                    className={cn('quill-menu__content', className)}
                    {...props}
                >
                    <div className="quill-menu__scroller scroll-mask-y-4 scroll-py-4">{children}</div>
                </ContextMenuPrimitive.Popup>
            </ContextMenuPrimitive.Positioner>
        </ContextMenuPrimitive.Portal>
    )
})

const ContextMenuGroup = React.forwardRef<
    React.ComponentRef<typeof ContextMenuPrimitive.Group>,
    ContextMenuPrimitive.Group.Props
>(function ContextMenuGroup({ ...props }, ref) {
    return <ContextMenuPrimitive.Group ref={ref} data-slot="context-menu-group" {...props} />
})

const ContextMenuLabel = React.forwardRef<
    React.ComponentRef<typeof ContextMenuPrimitive.GroupLabel>,
    ContextMenuPrimitive.GroupLabel.Props & {
        inset?: boolean
    }
>(function ContextMenuLabel({ className, inset, ...props }, ref) {
    return (
        <ContextMenuPrimitive.GroupLabel
            ref={ref}
            data-slot="context-menu-label"
            data-inset={inset}
            className={cn('px-2 py-1.5 text-xs text-muted-foreground', inset && 'quill-menu-item--inset', className)}
            {...props}
        />
    )
})

const ContextMenuItem = React.forwardRef<
    React.ComponentRef<typeof ContextMenuPrimitive.Item>,
    ContextMenuPrimitive.Item.Props & {
        inset?: boolean
        variant?: 'default' | 'destructive'
    }
>(function ContextMenuItem({ className, inset, variant = 'default', children, ...props }, ref) {
    return (
        <ContextMenuPrimitive.Item
            ref={ref}
            data-slot="context-menu-item"
            data-inset={inset}
            data-variant={variant}
            className={cn(
                "group/context-menu-item relative flex cursor-default items-center outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                inset && 'quill-menu-item--inset',
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button variant={variant} size="row" left />}
            {...props}
        >
            {children}
        </ContextMenuPrimitive.Item>
    )
})

function ContextMenuSub({ ...props }: ContextMenuPrimitive.SubmenuRoot.Props): React.ReactElement {
    return <ContextMenuPrimitive.SubmenuRoot data-slot="context-menu-sub" {...props} />
}

const ContextMenuSubTrigger = React.forwardRef<
    React.ComponentRef<typeof ContextMenuPrimitive.SubmenuTrigger>,
    ContextMenuPrimitive.SubmenuTrigger.Props & {
        inset?: boolean
    }
>(function ContextMenuSubTrigger({ className, inset, children, ...props }, ref) {
    return (
        <ContextMenuPrimitive.SubmenuTrigger
            ref={ref}
            data-slot="context-menu-sub-trigger"
            data-inset={inset}
            className={cn(
                "flex cursor-default items-center outline-hidden select-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                inset && 'quill-menu-item--inset',
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button size="row" left />}
            {...props}
        >
            {children}
            <ChevronRightIcon className="rtl:rotate-180 ms-auto" />
        </ContextMenuPrimitive.SubmenuTrigger>
    )
})

const ContextMenuSubContent = React.forwardRef<
    React.ComponentRef<typeof ContextMenuContent>,
    React.ComponentProps<typeof ContextMenuContent>
>(function ContextMenuSubContent(
    { className, align = 'start', alignOffset = -3, side = 'inline-end', sideOffset = 0, ...props },
    ref
) {
    return (
        <ContextMenuContent
            ref={ref}
            data-slot="context-menu-sub-content"
            className={cn('quill-menu__sub-content w-auto', className)}
            align={align}
            alignOffset={alignOffset}
            side={side}
            sideOffset={sideOffset}
            {...props}
        />
    )
})

const ContextMenuCheckboxItem = React.forwardRef<
    React.ComponentRef<typeof ContextMenuPrimitive.CheckboxItem>,
    ContextMenuPrimitive.CheckboxItem.Props & {
        inset?: boolean
    }
>(function ContextMenuCheckboxItem({ className, children, checked, inset, ...props }, ref) {
    return (
        <ContextMenuPrimitive.CheckboxItem
            ref={ref}
            data-slot="context-menu-checkbox-item"
            data-inset={inset}
            className={cn(
                "quill-menu-item--inset relative flex cursor-default items-center pe-2 outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button size="row" left />}
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
})

const ContextMenuRadioGroup = React.forwardRef<
    React.ComponentRef<typeof ContextMenuPrimitive.RadioGroup>,
    ContextMenuPrimitive.RadioGroup.Props
>(function ContextMenuRadioGroup({ ...props }, ref) {
    return <ContextMenuPrimitive.RadioGroup ref={ref} data-slot="context-menu-radio-group" {...props} />
})

const ContextMenuRadioItem = React.forwardRef<
    React.ComponentRef<typeof ContextMenuPrimitive.RadioItem>,
    ContextMenuPrimitive.RadioItem.Props & {
        inset?: boolean
    }
>(function ContextMenuRadioItem({ className, children, inset, ...props }, ref) {
    return (
        <ContextMenuPrimitive.RadioItem
            ref={ref}
            data-slot="context-menu-radio-item"
            data-inset={inset}
            className={cn(
                "quill-menu-item--inset relative flex cursor-default items-center pe-2 outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button size="row" left />}
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
})

const ContextMenuSeparator = React.forwardRef<
    React.ComponentRef<typeof ContextMenuPrimitive.Separator>,
    ContextMenuPrimitive.Separator.Props
>(function ContextMenuSeparator({ className, ...props }, ref) {
    return (
        <ContextMenuPrimitive.Separator
            ref={ref}
            data-slot="context-menu-separator"
            className={cn('quill-menu__separator', className)}
            {...props}
        />
    )
})

const ContextMenuShortcut = React.forwardRef<React.ComponentRef<typeof Kbd>, React.ComponentProps<typeof Kbd>>(
    function ContextMenuShortcut({ className, ...props }, ref) {
        return (
            <Kbd
                ref={ref}
                data-slot="context-menu-shortcut"
                className={cn('quill-menu__shortcut', className)}
                {...props}
            />
        )
    }
)

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
