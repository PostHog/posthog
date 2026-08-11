import './menu.css'

import { ContextMenu as ContextMenuPrimitive } from '@base-ui/react/context-menu'
import { ChevronRightIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { Checkbox } from './checkbox'
import { Kbd } from './kbd'
import { cn } from './lib/utils'
import { RadioIndicator } from './radio-group'

/**
 * A component that creates a context menu activated by right clicking or long pressing.
 * Doesn't render its own HTML element.
 *
 * Documentation: [Base UI Context Menu](https://base-ui.com/react/components/context-menu)
 *
 * @baseui ContextMenu.Root
 */
function ContextMenu({ ...props }: ContextMenuPrimitive.Root.Props): React.ReactElement {
    return <ContextMenuPrimitive.Root data-slot="context-menu" {...props} />
}

/**
 * A portal element that moves the popup to a different part of the DOM.
 * By default, the portal element is appended to `<body>`.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui ContextMenu.Portal
 */
function ContextMenuPortal({ ...props }: ContextMenuPrimitive.Portal.Props): React.ReactElement {
    return <ContextMenuPrimitive.Portal data-slot="context-menu-portal" {...props} />
}

/**
 * An area that opens the menu on right click or long press.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Context Menu](https://base-ui.com/react/components/context-menu)
 *
 * @baseui ContextMenu.Trigger
 */
function ContextMenuTrigger({ className, ...props }: ContextMenuPrimitive.Trigger.Props): React.ReactElement {
    return (
        <ContextMenuPrimitive.Trigger
            data-slot="context-menu-trigger"
            className={cn('select-none', className)}
            {...props}
        />
    )
}

/**
 * A container for the menu items.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui ContextMenu.Popup
 */
function ContextMenuContent({
    className,
    align = 'start',
    alignOffset = 4,
    side = 'inline-end',
    sideOffset = 0,
    children,
    ...props
}: ContextMenuPrimitive.Popup.Props &
    Pick<ContextMenuPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset'>): React.ReactElement {
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
                    data-slot="context-menu-content"
                    className={cn('quill-menu__content', className)}
                    {...props}
                >
                    <div className="quill-menu__scroller scroll-mask-y-4 scroll-py-4">{children}</div>
                </ContextMenuPrimitive.Popup>
            </ContextMenuPrimitive.Positioner>
        </ContextMenuPrimitive.Portal>
    )
}

/**
 * Groups related menu items with the corresponding label.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui ContextMenu.Group
 */
function ContextMenuGroup({ ...props }: ContextMenuPrimitive.Group.Props): React.ReactElement {
    return <ContextMenuPrimitive.Group data-slot="context-menu-group" {...props} />
}

/**
 * An accessible label that is automatically associated with its parent group.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui ContextMenu.GroupLabel
 */
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
            className={cn('px-2 py-1.5 text-xs text-muted-foreground', inset && 'quill-menu-item--inset', className)}
            {...props}
        />
    )
}

/**
 * An individual interactive item in the menu.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui ContextMenu.Item
 */
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
                "group/context-menu-item relative flex cursor-default items-center outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                inset && 'quill-menu-item--inset',
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button variant={variant} className="w-full font-normal" left />}
            {...props}
        >
            {children}
        </ContextMenuPrimitive.Item>
    )
}

/**
 * Groups all parts of a submenu.
 * Doesn't render its own HTML element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui ContextMenu.SubmenuRoot
 */
function ContextMenuSub({ ...props }: ContextMenuPrimitive.SubmenuRoot.Props): React.ReactElement {
    return <ContextMenuPrimitive.SubmenuRoot data-slot="context-menu-sub" {...props} />
}

/**
 * A menu item that opens a submenu.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui ContextMenu.SubmenuTrigger
 */
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
                "flex cursor-default items-center outline-hidden select-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                inset && 'quill-menu-item--inset',
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button className="w-full font-normal" left />}
            {...props}
        >
            {children}
            <ChevronRightIcon className="rtl:rotate-180 ms-auto" />
        </ContextMenuPrimitive.SubmenuTrigger>
    )
}

function ContextMenuSubContent({
    className,
    align = 'start',
    alignOffset = -3,
    side = 'inline-end',
    sideOffset = 0,
    ...props
}: React.ComponentProps<typeof ContextMenuContent>): React.ReactElement {
    return (
        <ContextMenuContent
            data-slot="context-menu-sub-content"
            className={cn('quill-menu__sub-content w-auto', className)}
            align={align}
            alignOffset={alignOffset}
            side={side}
            sideOffset={sideOffset}
            {...props}
        />
    )
}

/**
 * A menu item that toggles a setting on or off.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui ContextMenu.CheckboxItem
 */
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
                "quill-menu-item--inset relative flex cursor-default items-center pe-2 text-xs outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
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

/**
 * Groups related radio items.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui ContextMenu.RadioGroup
 */
function ContextMenuRadioGroup({ ...props }: ContextMenuPrimitive.RadioGroup.Props): React.ReactElement {
    return <ContextMenuPrimitive.RadioGroup data-slot="context-menu-radio-group" {...props} />
}

/**
 * A menu item that works like a radio button in a given group.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui ContextMenu.RadioItem
 */
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
                "quill-menu-item--inset relative flex cursor-default items-center pe-2 outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
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

/**
 * A separator element accessible to screen readers.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Separator](https://base-ui.com/react/components/separator)
 *
 * @baseui ContextMenu.Separator
 */
function ContextMenuSeparator({ className, ...props }: ContextMenuPrimitive.Separator.Props): React.ReactElement {
    return (
        <ContextMenuPrimitive.Separator
            data-slot="context-menu-separator"
            className={cn('quill-menu__separator', className)}
            {...props}
        />
    )
}

function ContextMenuShortcut({ className, ...props }: React.ComponentProps<typeof Kbd>): React.ReactElement {
    return <Kbd data-slot="context-menu-shortcut" className={cn('quill-menu__shortcut', className)} {...props} />
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
