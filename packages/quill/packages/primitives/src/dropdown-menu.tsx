import './menu.css'

import { Menu as MenuPrimitive } from '@base-ui/react/menu'
import { ChevronRightIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { Checkbox } from './checkbox'
import { Kbd } from './kbd'
import { cn } from './lib/utils'
import { MenuLabel } from './menu-label'
import { RadioIndicator } from './radio-group'

/**
 * Groups all parts of the menu.
 * Doesn't render its own HTML element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui Menu.Root
 */
function DropdownMenu({ ...props }: MenuPrimitive.Root.Props): React.ReactElement {
    return <MenuPrimitive.Root data-slot="dropdown-menu" {...props} />
}

/**
 * A portal element that moves the popup to a different part of the DOM.
 * By default, the portal element is appended to `<body>`.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui Menu.Portal
 */
function DropdownMenuPortal({ ...props }: MenuPrimitive.Portal.Props): React.ReactElement {
    return <MenuPrimitive.Portal data-slot="dropdown-menu-portal" {...props} />
}

/**
 * A button that opens the menu.
 * Renders a `<button>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui Menu.Trigger
 */
function DropdownMenuTrigger({ ...props }: MenuPrimitive.Trigger.Props): React.ReactElement {
    return <MenuPrimitive.Trigger data-slot="dropdown-menu-trigger" {...props} />
}

/**
 * A container for the menu items.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui Menu.Popup
 */
function DropdownMenuContent({
    align = 'start',
    alignOffset = 0,
    side = 'bottom',
    sideOffset = 4,
    className,
    anchor,
    children,
    ...props
}: MenuPrimitive.Popup.Props &
    Pick<
        MenuPrimitive.Positioner.Props,
        'align' | 'alignOffset' | 'side' | 'sideOffset' | 'anchor'
    >): React.ReactElement {
    return (
        <MenuPrimitive.Portal>
            <MenuPrimitive.Positioner
                data-quill
                data-quill-portal="popover"
                className="isolate outline-none"
                align={align}
                alignOffset={alignOffset}
                side={side}
                sideOffset={sideOffset}
                anchor={anchor}
            >
                <MenuPrimitive.Popup
                    data-slot="dropdown-menu-content"
                    className={cn('quill-menu__content w-(--anchor-width)', className)}
                    {...props}
                >
                    <div className="quill-menu__scroller scroll-mask-y-4 scroll-py-4">{children}</div>
                </MenuPrimitive.Popup>
            </MenuPrimitive.Positioner>
        </MenuPrimitive.Portal>
    )
}

/**
 * Groups related menu items with the corresponding label.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui Menu.Group
 */
function DropdownMenuGroup({ ...props }: MenuPrimitive.Group.Props): React.ReactElement {
    return <MenuPrimitive.Group data-slot="dropdown-menu-group" {...props} />
}

/**
 * An accessible label that is automatically associated with its parent group.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui Menu.GroupLabel
 */
function DropdownMenuLabel({
    className,
    inset,
    ...props
}: MenuPrimitive.GroupLabel.Props & {
    inset?: boolean
}): React.ReactElement {
    return (
        <MenuPrimitive.GroupLabel
            data-slot="dropdown-menu-label"
            data-inset={inset}
            className={cn(inset && 'quill-menu-item--inset', className)}
            render={<MenuLabel />}
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
 * @baseui Menu.Item
 */
function DropdownMenuItem({
    className,
    inset,
    variant = 'default',
    ...props
}: MenuPrimitive.Item.Props & {
    inset?: boolean
    variant?: 'default' | 'destructive'
}): React.ReactElement {
    return (
        <MenuPrimitive.Item
            data-slot="dropdown-menu-item"
            data-inset={inset}
            data-variant={variant}
            className={cn(
                "group/dropdown-menu-item relative flex cursor-default items-center text-xs/relaxed outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                // Destructive menu items are transparent at rest (red text only) and get a red
                // tint on hover/highlight — Button's standalone `destructive` variant (filled at
                // rest) is wrong inside a menu, so the inner Button always stays `default`.
                // Disabled destructive mirrors the disabled destructive Button: 50%-mix red fill
                // under the item-level opacity-50.
                'data-[variant=destructive]:text-destructive-foreground data-[variant=destructive]:hover:text-destructive-foreground data-[variant=destructive]:[&_svg]:text-destructive-foreground data-[variant=destructive]:hover:bg-destructive/10 data-[variant=destructive]:focus:bg-destructive/10 data-[variant=destructive]:data-highlighted:bg-destructive/10 dark:data-[variant=destructive]:hover:bg-destructive/20 dark:data-[variant=destructive]:focus:bg-destructive/20 dark:data-[variant=destructive]:data-highlighted:bg-destructive/20 data-[variant=destructive]:data-disabled:bg-destructive/50',
                inset && 'quill-menu-item--inset',
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button variant="default" className="w-full font-normal [&_kbd]:ml-auto" left />}
            {...props}
        />
    )
}

/**
 * Groups all parts of a submenu.
 * Doesn't render its own HTML element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui Menu.SubmenuRoot
 */
function DropdownMenuSub({ ...props }: MenuPrimitive.SubmenuRoot.Props): React.ReactElement {
    return <MenuPrimitive.SubmenuRoot data-slot="dropdown-menu-sub" {...props} />
}

/**
 * A menu item that opens a submenu.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui Menu.SubmenuTrigger
 */
function DropdownMenuSubTrigger({
    className,
    inset,
    children,
    ...props
}: MenuPrimitive.SubmenuTrigger.Props & {
    inset?: boolean
}): React.ReactElement {
    return (
        <MenuPrimitive.SubmenuTrigger
            data-slot="dropdown-menu-sub-trigger"
            data-inset={inset}
            className={cn(
                "flex cursor-default items-center text-xs outline-hidden select-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
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
        </MenuPrimitive.SubmenuTrigger>
    )
}

function DropdownMenuSubContent({
    align = 'start',
    alignOffset = -3,
    side = 'inline-end',
    sideOffset = 0,
    className,
    ...props
}: React.ComponentProps<typeof DropdownMenuContent>): React.ReactElement {
    return (
        <DropdownMenuContent
            data-slot="dropdown-menu-sub-content"
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
 * @baseui Menu.CheckboxItem
 */
function DropdownMenuCheckboxItem({
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
            data-slot="dropdown-menu-checkbox-item"
            data-inset={inset}
            className={cn(
                "quill-menu-item--inset relative flex cursor-default items-center pe-2 text-xs outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            checked={checked}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button className="w-full font-normal" left />}
            {...props}
        >
            <span
                className="pointer-events-none absolute start-2 flex items-center justify-center"
                data-slot="dropdown-menu-checkbox-item-indicator"
            >
                <Checkbox size="sm" tabIndex={-1} />
                <MenuPrimitive.CheckboxItemIndicator className="absolute">
                    <Checkbox size="sm" checked tabIndex={-1} />
                </MenuPrimitive.CheckboxItemIndicator>
            </span>
            {children}
        </MenuPrimitive.CheckboxItem>
    )
}

/**
 * Groups related radio items.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui Menu.RadioGroup
 */
function DropdownMenuRadioGroup({ ...props }: MenuPrimitive.RadioGroup.Props): React.ReactElement {
    return <MenuPrimitive.RadioGroup data-slot="dropdown-menu-radio-group" {...props} />
}

/**
 * A menu item that works like a radio button in a given group.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Menu](https://base-ui.com/react/components/menu)
 *
 * @baseui Menu.RadioItem
 */
function DropdownMenuRadioItem({
    className,
    children,
    inset,
    ...props
}: MenuPrimitive.RadioItem.Props & {
    inset?: boolean
}): React.ReactElement {
    return (
        <MenuPrimitive.RadioItem
            data-slot="dropdown-menu-radio-item"
            data-inset={inset}
            className={cn(
                "quill-menu-item--inset relative flex min-h-7 cursor-default items-center pe-2 text-xs outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button className="w-full font-normal" left />}
            {...props}
        >
            <span
                className="pointer-events-none absolute start-2 flex items-center justify-center"
                data-slot="dropdown-menu-radio-item-indicator"
            >
                <RadioIndicator size="sm" />
                <MenuPrimitive.RadioItemIndicator className="absolute">
                    <RadioIndicator size="sm" checked />
                </MenuPrimitive.RadioItemIndicator>
            </span>
            {children}
        </MenuPrimitive.RadioItem>
    )
}

/**
 * A separator element accessible to screen readers.
 * Renders a `<div>` element.
 *
 * Documentation: [Base UI Separator](https://base-ui.com/react/components/separator)
 *
 * @baseui Menu.Separator
 */
function DropdownMenuSeparator({ className, ...props }: MenuPrimitive.Separator.Props): React.ReactElement {
    return (
        <MenuPrimitive.Separator
            data-slot="dropdown-menu-separator"
            className={cn('quill-menu__separator', className)}
            {...props}
        />
    )
}

/**
 * Tri-state for a select-all action over a list of selectable values.
 *  - `none`: nothing selected
 *  - `some`: at least one but not all selected (indeterminate)
 *  - `all`:  every value selected
 */
type SelectAllState = 'none' | 'some' | 'all'

type UseSelectAllResult = {
    state: SelectAllState
    isAllSelected: boolean
    toggle: () => void
}

/**
 * Headless hook for a "select all / deselect all" action paired with a list
 * of `DropdownMenuCheckboxItem`s. Consumer owns rendering and stays in
 * control of the selection state.
 *
 * Comparison is reference equality unless `getKey` is supplied — pass a key
 * extractor when `values` are objects whose identity isn't stable across
 * renders (e.g. fetched from an API).
 *
 * @example
 * const ALL = ['a', 'b', 'c']
 * const [selected, setSelected] = useState<string[]>([])
 * const { isAllSelected, toggle } = useDropdownMenuSelectAll(ALL, selected, setSelected)
 *
 * <DropdownMenuItem closeOnClick={false} onClick={toggle}>
 *     {isAllSelected ? 'Deselect all' : 'Select all'}
 * </DropdownMenuItem>
 */
function useDropdownMenuSelectAll<T>(
    values: readonly T[],
    selected: readonly T[],
    onChange: (next: T[]) => void,
    getKey?: (value: T) => string | number
): UseSelectAllResult {
    const selectedKeys = React.useMemo(() => {
        const keys = new Set<unknown>()
        for (const v of selected) {
            keys.add(getKey ? getKey(v) : v)
        }
        return keys
    }, [selected, getKey])

    const matched = values.reduce((count, v) => {
        const key = getKey ? getKey(v) : v
        return count + (selectedKeys.has(key) ? 1 : 0)
    }, 0)

    const state: SelectAllState = matched === 0 ? 'none' : matched >= values.length ? 'all' : 'some'
    const isAllSelected = state === 'all'

    const toggle = React.useCallback(() => {
        onChange(isAllSelected ? [] : values.slice())
    }, [isAllSelected, onChange, values])

    return { state, isAllSelected, toggle }
}

/**
 * Convenience component that renders a `DropdownMenuItem` whose label flips
 * between `selectLabel` ("Select all") and `deselectLabel` ("Deselect all")
 * based on the current selection state. The menu stays open after toggle so
 * users can keep adjusting items.
 *
 * For full control, use `useDropdownMenuSelectAll` directly and render your
 * own item — or pass a render-prop child:
 *
 * @example
 * <DropdownMenuSelectAll values={ALL} selected={selected} onChange={setSelected} />
 *
 * <DropdownMenuSelectAll values={ALL} selected={selected} onChange={setSelected}>
 *     {({ state, toggle }) => (
 *         <DropdownMenuItem closeOnClick={false} onClick={toggle}>
 *             {state === 'all' ? 'Clear' : 'Pick everything'}
 *             {state === 'some' && ' (partial)'}
 *         </DropdownMenuItem>
 *     )}
 * </DropdownMenuSelectAll>
 */
function DropdownMenuSelectAll<T>({
    values,
    selected,
    onChange,
    getKey,
    selectLabel = 'Select all',
    deselectLabel = 'Deselect all',
    children,
    ...itemProps
}: {
    values: readonly T[]
    selected: readonly T[]
    onChange: (next: T[]) => void
    getKey?: (value: T) => string | number
    selectLabel?: React.ReactNode
    deselectLabel?: React.ReactNode
    children?: (result: UseSelectAllResult) => React.ReactNode
} & Omit<
    React.ComponentProps<typeof DropdownMenuItem>,
    'children' | 'onClick' | 'onChange' | 'closeOnClick' | 'data-state'
>): React.ReactElement {
    const result = useDropdownMenuSelectAll(values, selected, onChange, getKey)

    if (children) {
        return <>{children(result)}</>
    }

    return (
        <DropdownMenuItem
            {...itemProps}
            data-slot="dropdown-menu-select-all"
            data-state={result.state}
            closeOnClick={false}
            onClick={result.toggle}
        >
            {result.isAllSelected ? deselectLabel : selectLabel}
        </DropdownMenuItem>
    )
}

function DropdownMenuShortcut({ className, ...props }: React.ComponentProps<typeof Kbd>): React.ReactElement {
    return <Kbd data-slot="dropdown-menu-shortcut" className={cn('quill-menu__shortcut', className)} {...props} />
}

export {
    DropdownMenu,
    DropdownMenuPortal,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuItem,
    DropdownMenuCheckboxItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSelectAll,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
    DropdownMenuSub,
    DropdownMenuSubTrigger,
    DropdownMenuSubContent,
    useDropdownMenuSelectAll,
}
export type { SelectAllState, UseSelectAllResult }
