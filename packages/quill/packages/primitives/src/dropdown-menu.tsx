import './menu.css'

import { Menu as MenuPrimitive } from '@base-ui/react/menu'
import { ChevronRightIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from './button'
import { Checkbox } from './checkbox'
import { Kbd } from './kbd'
import { cn } from './lib/utils'
import { MenuItemBody } from './menu-item-body'
import { MenuLabel } from './menu-label'
import { RadioIndicator } from './radio-group'
import { hasTooltipContent, withTooltip } from './with-tooltip'

type MenuItemExtras = {
    /** Text shown in a tooltip beside the item. */
    tooltip?: React.ReactNode
    /** Disables the item and says why in a tooltip beside it. Takes the place of `tooltip` while set. */
    disabledReason?: React.ReactNode
}

type DescribedMenuItemExtras = MenuItemExtras & {
    /** A muted second line under the label. The row grows to fit it, and its text lines up past a leading icon. */
    description?: React.ReactNode
}

/** Disabled items ignore the pointer, so the tooltip listens on a wrapper and opens beside the row. */
function withItemTooltip(
    item: React.ReactElement,
    { tooltip, disabledReason }: Pick<MenuItemExtras, 'tooltip' | 'disabledReason'>
): React.ReactElement {
    const content = hasTooltipContent(disabledReason) ? disabledReason : tooltip
    return withTooltip(item, content, { target: 'block', side: 'inline-end' })
}



function DropdownMenu({ ...props }: MenuPrimitive.Root.Props): React.ReactElement {
    return <MenuPrimitive.Root data-slot="dropdown-menu" {...props} />
}

function DropdownMenuPortal({ ...props }: MenuPrimitive.Portal.Props): React.ReactElement {
    return <MenuPrimitive.Portal data-slot="dropdown-menu-portal" {...props} />
}

const DropdownMenuTrigger = React.forwardRef<HTMLButtonElement, MenuPrimitive.Trigger.Props>(
    function DropdownMenuTrigger(props, ref) {
        return <MenuPrimitive.Trigger ref={ref} data-slot="dropdown-menu-trigger" {...props} />
    }
)

const DropdownMenuContent = React.forwardRef<
    React.ComponentRef<typeof MenuPrimitive.Popup>,
    MenuPrimitive.Popup.Props &
        Pick<MenuPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset' | 'anchor'>
>(function DropdownMenuContent(
    { align = 'start', alignOffset = 0, side = 'bottom', sideOffset = 4, className, anchor, children, ...props },
    ref
) {
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
                    ref={ref}
                    data-slot="dropdown-menu-content"
                    className={cn('quill-menu__content w-max min-w-(--anchor-width) max-w-(--available-width)', className)}
                    {...props}
                >
                    <div className="quill-menu__scroller scroll-mask-y-4 scroll-py-4">{children}</div>
                </MenuPrimitive.Popup>
            </MenuPrimitive.Positioner>
        </MenuPrimitive.Portal>
    )
})

const DropdownMenuGroup = React.forwardRef<React.ComponentRef<typeof MenuPrimitive.Group>, MenuPrimitive.Group.Props>(
    function DropdownMenuGroup({ ...props }, ref) {
        return <MenuPrimitive.Group ref={ref} data-slot="dropdown-menu-group" {...props} />
    }
)

const DropdownMenuLabel = React.forwardRef<
    React.ComponentRef<typeof MenuPrimitive.GroupLabel>,
    MenuPrimitive.GroupLabel.Props & {
        inset?: boolean
    }
>(function DropdownMenuLabel({ className, inset, ...props }, ref) {
    return (
        <MenuPrimitive.GroupLabel
            ref={ref}
            data-slot="dropdown-menu-label"
            data-inset={inset}
            className={cn(inset && 'quill-menu-item--inset', className)}
            render={<MenuLabel />}
            {...props}
        />
    )
})

const DropdownMenuItem = React.forwardRef<
    React.ComponentRef<typeof MenuPrimitive.Item>,
    MenuPrimitive.Item.Props &
        DescribedMenuItemExtras & {
            inset?: boolean
            variant?: 'default' | 'destructive'
        }
>(function DropdownMenuItem(
    { className, inset, variant = 'default', disabled, tooltip, disabledReason, description, children, ...props },
    ref
) {
    const described = hasTooltipContent(description)
    return withItemTooltip(
        <MenuPrimitive.Item
            ref={ref}
            data-slot="dropdown-menu-item"
            data-inset={inset}
            data-variant={variant}
            disabled={disabled || hasTooltipContent(disabledReason)}
            className={cn(
                "group/dropdown-menu-item relative flex cursor-default items-center outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                inset && 'quill-menu-item--inset',
                described && 'quill-menu-item--described',
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button variant={variant} size="row" className="[&_kbd]:ml-auto" left />}
            {...props}
        >
            {described ? <MenuItemBody description={description}>{children}</MenuItemBody> : children}
        </MenuPrimitive.Item>,
        { tooltip, disabledReason }
    )
})

function DropdownMenuSub({ ...props }: MenuPrimitive.SubmenuRoot.Props): React.ReactElement {
    return <MenuPrimitive.SubmenuRoot data-slot="dropdown-menu-sub" {...props} />
}

const DropdownMenuSubTrigger = React.forwardRef<
    React.ComponentRef<typeof MenuPrimitive.SubmenuTrigger>,
    MenuPrimitive.SubmenuTrigger.Props &
        DescribedMenuItemExtras & {
            inset?: boolean
        }
>(function DropdownMenuSubTrigger(
    { className, inset, disabled, tooltip, disabledReason, description, children, ...props },
    ref
) {
    const described = hasTooltipContent(description)
    return withItemTooltip(
        <MenuPrimitive.SubmenuTrigger
            ref={ref}
            data-slot="dropdown-menu-sub-trigger"
            data-inset={inset}
            disabled={disabled || hasTooltipContent(disabledReason)}
            className={cn(
                "flex cursor-default items-center outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                inset && 'quill-menu-item--inset',
                described && 'quill-menu-item--described',
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button size="row" left />}
            {...props}
        >
            {described ? <MenuItemBody description={description}>{children}</MenuItemBody> : children}
            <ChevronRightIcon className="rtl:rotate-180 ms-auto" />
        </MenuPrimitive.SubmenuTrigger>,
        { tooltip, disabledReason }
    )
})

const DropdownMenuSubContent = React.forwardRef<
    React.ComponentRef<typeof DropdownMenuContent>,
    React.ComponentProps<typeof DropdownMenuContent>
>(function DropdownMenuSubContent(
    { align = 'start', alignOffset = -3, side = 'inline-end', sideOffset = 0, className, ...props },
    ref
) {
    return (
        <DropdownMenuContent
            ref={ref}
            data-slot="dropdown-menu-sub-content"
            className={cn('quill-menu__sub-content w-auto', className)}
            align={align}
            alignOffset={alignOffset}
            side={side}
            sideOffset={sideOffset}
            {...props}
        />
    )
})

const DropdownMenuCheckboxItem = React.forwardRef<
    React.ComponentRef<typeof MenuPrimitive.CheckboxItem>,
    MenuPrimitive.CheckboxItem.Props &
        MenuItemExtras & {
            inset?: boolean
        }
>(function DropdownMenuCheckboxItem(
    { className, children, checked, inset, disabled, tooltip, disabledReason, ...props },
    ref
) {
    return withItemTooltip(
        <MenuPrimitive.CheckboxItem
            ref={ref}
            data-slot="dropdown-menu-checkbox-item"
            data-inset={inset}
            disabled={disabled || hasTooltipContent(disabledReason)}
            className={cn(
                "quill-menu-item--inset relative flex cursor-default items-center pe-2 outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            checked={checked}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button size="row" left />}
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
        </MenuPrimitive.CheckboxItem>,
        { tooltip, disabledReason }
    )
})

const DropdownMenuRadioGroup = React.forwardRef<
    React.ComponentRef<typeof MenuPrimitive.RadioGroup>,
    MenuPrimitive.RadioGroup.Props
>(function DropdownMenuRadioGroup({ ...props }, ref) {
    return <MenuPrimitive.RadioGroup ref={ref} data-slot="dropdown-menu-radio-group" {...props} />
})

const DropdownMenuRadioItem = React.forwardRef<
    React.ComponentRef<typeof MenuPrimitive.RadioItem>,
    MenuPrimitive.RadioItem.Props &
        MenuItemExtras & {
            inset?: boolean
        }
>(function DropdownMenuRadioItem({ className, children, inset, disabled, tooltip, disabledReason, ...props }, ref) {
    return withItemTooltip(
        <MenuPrimitive.RadioItem
            ref={ref}
            data-slot="dropdown-menu-radio-item"
            data-inset={inset}
            disabled={disabled || hasTooltipContent(disabledReason)}
            className={cn(
                "quill-menu-item--inset relative flex min-h-7 cursor-default items-center pe-2 outline-hidden select-none data-disabled:pointer-events-none data-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-3.5",
                className
            )}
            // The default render is a real <button>; only declare nativeButton when the
            // caller hasn't overridden render (their element may not be a button).
            nativeButton={!('render' in props)}
            render={<Button size="row" left />}
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
        </MenuPrimitive.RadioItem>,
        { tooltip, disabledReason }
    )
})

const DropdownMenuSeparator = React.forwardRef<
    React.ComponentRef<typeof MenuPrimitive.Separator>,
    MenuPrimitive.Separator.Props
>(function DropdownMenuSeparator({ className, ...props }, ref) {
    return (
        <MenuPrimitive.Separator
            ref={ref}
            data-slot="dropdown-menu-separator"
            className={cn('quill-menu__separator', className)}
            {...props}
        />
    )
})

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

const DropdownMenuShortcut = React.forwardRef<React.ComponentRef<typeof Kbd>, React.ComponentProps<typeof Kbd>>(
    function DropdownMenuShortcut({ className, ...props }, ref) {
        return (
            <Kbd
                ref={ref}
                data-slot="dropdown-menu-shortcut"
                className={cn('quill-menu__shortcut', className)}
                {...props}
            />
        )
    }
)

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
