import * as React from 'react'

import {
    cn,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuFilterProvider,
    DropdownMenuGroup,
    DropdownMenuInput,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuList,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
    Popover,
    PopoverContent,
} from '@posthog/quill-primitives'

import {
    type ActionMenuItem,
    type ActionMenuPanel,
    type ActionMenuRadio,
    type ActionMenuRadioOption,
    type ActionMenuSearchResult,
    type ActionMenuSubmenu,
    collectDestructive,
    hasRows,
    searchActionMenu,
} from './action-menu-tree'

export interface ActionMenuSelectDetails {
    path: string[]
    fromSearch: boolean
}

export interface ActionMenuProps {
    items: ActionMenuItem[]
    trigger: React.ReactElement
    triggerChildren?: React.ReactNode
    searchable?: boolean
    searchPlaceholder?: string
    emptyLabel?: string
    align?: 'start' | 'center' | 'end'
    onOpenChange?: (open: boolean) => void
    onSubmenuOpenChange?: (item: ActionMenuSubmenu, open: boolean, path: string[]) => void
    onItemSelect?: (item: ActionMenuItem, details: ActionMenuSelectDetails) => void
    /** Fires once per opening, on the first character typed in the search. */
    onSearch?: () => void
}

interface RenderContextValue {
    fromSearch: boolean
    onItemSelect?: ActionMenuProps['onItemSelect']
    onSubmenuOpenChange?: ActionMenuProps['onSubmenuOpenChange']
    openPanel: (item: ActionMenuPanel) => void
}

const RenderContext = React.createContext<RenderContextValue>({ fromSearch: false, openPanel: () => {} })

const ICON_SPACER = <span aria-hidden className="size-3.5 shrink-0" />

function Ellipsis(): React.ReactElement {
    // `-ms-2` cancels the row's gap so the ellipsis sits against the label.
    return (
        <span aria-hidden className="-ms-2">
            …
        </span>
    )
}

function PathPrefix({ path }: { path: string[] }): React.ReactElement | null {
    if (path.length === 0) {
        return null
    }
    return <span className="text-muted-foreground">{path.map((segment) => `${segment} › `).join('')}</span>
}

function RowLabel({
    icon,
    path,
    label,
}: {
    icon?: React.ReactNode
    path: string[]
    label: string
}): React.ReactElement {
    return (
        <>
            {icon ?? ICON_SPACER}
            <span className="truncate">
                <PathPrefix path={path} />
                {label}
            </span>
        </>
    )
}

function RadioOptionRow({
    radio,
    option,
    path,
}: {
    radio: ActionMenuRadio
    option: ActionMenuRadioOption
    path: string[]
}): React.ReactElement {
    const { fromSearch, onItemSelect } = React.useContext(RenderContext)
    return (
        <DropdownMenuRadioItem
            value={option.value}
            disabledReason={option.disabledReason}
            data-attr={radio.dataAttr ? `${radio.dataAttr}-${option.value}` : undefined}
            onClick={() => onItemSelect?.(radio, { path, fromSearch })}
        >
            {option.icon}
            <span className="truncate">
                <PathPrefix path={path} />
                {option.label}
            </span>
        </DropdownMenuRadioItem>
    )
}

interface RowProps {
    item: ActionMenuItem
    path: string[]
    prefix: string[]
    hoisting: boolean
    depth: number
}

function SubmenuRow({
    item,
    path,
    prefix,
}: Omit<RowProps, 'item' | 'hoisting' | 'depth'> & { item: ActionMenuSubmenu }): React.ReactElement {
    const context = React.useContext(RenderContext)
    const { onSubmenuOpenChange } = context
    return (
        <DropdownMenuSub
            onOpenChange={(open) => {
                item.onOpenChange?.(open)
                onSubmenuOpenChange?.(item, open, path)
            }}
        >
            <DropdownMenuSubTrigger
                data-attr={item.dataAttr}
                disabledReason={item.disabledReason}
                tooltip={item.tooltip}
            >
                <RowLabel icon={item.icon} path={prefix} label={item.label} />
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                <RenderContext.Provider value={{ ...context, fromSearch: false }}>
                    <Rows items={item.items} path={[...path, item.label]} hoisting={false} depth={2} />
                </RenderContext.Provider>
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}

function Row({ item, path, prefix, hoisting, depth }: RowProps): React.ReactElement | null {
    const { fromSearch, onItemSelect, openPanel } = React.useContext(RenderContext)
    const select = (): void => onItemSelect?.(item, { path, fromSearch })

    switch (item.type) {
        case 'submenu': {
            if (depth === 1 && item.display !== 'submenu') {
                return (
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>{item.label}</DropdownMenuLabel>
                        <Rows items={item.items} path={[...path, item.label]} hoisting={hoisting} depth={2} />
                    </DropdownMenuGroup>
                )
            }
            return <SubmenuRow item={item} path={path} prefix={prefix} />
        }
        case 'checkbox':
            return (
                <DropdownMenuCheckboxItem
                    checked={item.checked}
                    onCheckedChange={(checked) => {
                        select()
                        item.onCheckedChange(checked)
                    }}
                    disabledReason={item.disabledReason}
                    tooltip={item.tooltip}
                    data-attr={item.dataAttr}
                >
                    <span className="truncate">
                        <PathPrefix path={prefix} />
                        {item.label}
                    </span>
                </DropdownMenuCheckboxItem>
            )
        case 'radio':
            return (
                <DropdownMenuGroup>
                    <DropdownMenuLabel>{item.label}</DropdownMenuLabel>
                    <DropdownMenuRadioGroup value={item.value} onValueChange={(value) => item.onValueChange(value)}>
                        {item.options.map((option) => (
                            <RadioOptionRow key={option.value} radio={item} option={option} path={path} />
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuGroup>
            )
        case 'panel':
            return (
                <DropdownMenuItem
                    data-attr={item.dataAttr}
                    disabledReason={item.disabledReason}
                    tooltip={item.tooltip}
                    onClick={() => {
                        select()
                        openPanel(item)
                    }}
                >
                    <RowLabel icon={item.icon} path={prefix} label={item.label} />
                    <Ellipsis />
                </DropdownMenuItem>
            )
        default:
            return (
                <DropdownMenuItem
                    data-attr={item.dataAttr}
                    variant={item.destructive ? 'destructive' : 'default'}
                    disabledReason={item.disabledReason}
                    tooltip={item.tooltip}
                    onClick={() => {
                        select()
                        item.onSelect()
                    }}
                >
                    <RowLabel icon={item.icon} path={prefix} label={item.label} />
                    {item.opensFloatingUi && !item.destructive && <Ellipsis />}
                    {item.shortcut && <DropdownMenuShortcut>{item.shortcut}</DropdownMenuShortcut>}
                </DropdownMenuItem>
            )
    }
}

function sectionKey(item: ActionMenuItem, depth: number): string | undefined {
    const isGroup = item.type === 'radio' || (item.type === 'submenu' && depth === 1 && item.display !== 'submenu')
    return isGroup ? `group:${item.id}` : item.section
}

function Rows({
    items,
    path,
    hoisting,
    depth,
}: {
    items: ActionMenuItem[]
    path: string[]
    hoisting: boolean
    depth: number
}): React.ReactElement {
    const shown = items.filter((item) => hasRows(item, hoisting))
    return (
        <>
            {shown.map((item, index) => {
                const separated = index > 0 && sectionKey(item, depth) !== sectionKey(shown[index - 1], depth)
                return (
                    <React.Fragment key={item.id}>
                        {separated && <DropdownMenuSeparator />}
                        <Row item={item} path={path} prefix={[]} hoisting={hoisting} depth={depth} />
                    </React.Fragment>
                )
            })}
        </>
    )
}

function TopLevel({ items }: { items: ActionMenuItem[] }): React.ReactElement {
    const shown = items.filter((item) => hasRows(item, true))
    const destructive = collectDestructive(items)
    return (
        <>
            {shown.map((item, index) => {
                const separated = index > 0 && item.section !== shown[index - 1].section
                return (
                    <React.Fragment key={item.id}>
                        {separated && <DropdownMenuSeparator />}
                        {item.type === 'submenu' ? (
                            <TopLevelSubmenu item={item} />
                        ) : (
                            <Row item={item} path={[]} prefix={[]} hoisting depth={0} />
                        )}
                    </React.Fragment>
                )
            })}
            {destructive.length > 0 && (
                <DropdownMenuGroup data-attr="action-menu-destructive">
                    {shown.length > 0 && <DropdownMenuSeparator />}
                    {destructive.map((item) => (
                        <Row key={item.id} item={item} path={[]} prefix={[]} hoisting={false} depth={0} />
                    ))}
                </DropdownMenuGroup>
            )}
        </>
    )
}

function TopLevelSubmenu({ item }: { item: ActionMenuSubmenu }): React.ReactElement {
    const { onSubmenuOpenChange } = React.useContext(RenderContext)
    return (
        <DropdownMenuSub
            onOpenChange={(open) => {
                item.onOpenChange?.(open)
                onSubmenuOpenChange?.(item, open, [])
            }}
        >
            <DropdownMenuSubTrigger data-attr={item.dataAttr} disabledReason={item.disabledReason}>
                <RowLabel icon={item.icon} path={[]} label={item.label} />
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                <Rows items={item.items} path={[item.label]} hoisting depth={1} />
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}

function SearchResults({
    results,
    emptyLabel,
}: {
    results: ActionMenuSearchResult[]
    emptyLabel: string
}): React.ReactElement {
    if (results.length === 0) {
        return (
            <div role="status" aria-live="polite" className="px-2 py-1.5 text-xs text-muted-foreground">
                {emptyLabel}
            </div>
        )
    }
    return (
        <>
            {results.map((result) =>
                result.kind === 'radio-option' ? (
                    <DropdownMenuRadioGroup
                        key={`${result.radio.id}:${result.option.value}`}
                        value={result.radio.value}
                        onValueChange={(value) => result.radio.onValueChange(value)}
                    >
                        <RadioOptionRow radio={result.radio} option={result.option} path={result.path} />
                    </DropdownMenuRadioGroup>
                ) : (
                    <Row
                        key={[...result.path, result.item.id].join('\u0000')}
                        item={result.item}
                        path={result.path}
                        prefix={result.path}
                        hoisting={false}
                        depth={2}
                    />
                )
            )}
        </>
    )
}

/**
 * A menu driven by an item tree. It opens on a search field above a short top level, where each top-level submenu is
 * one row and destructive rows come last. A query swaps the top level for one flat list of matches from every level,
 * each prefixed with its path ("Export › CSV").
 */
export function ActionMenu({
    items,
    trigger,
    triggerChildren,
    searchable = true,
    searchPlaceholder = 'Search actions',
    emptyLabel = 'No matching actions',
    align = 'start',
    onOpenChange,
    onSubmenuOpenChange,
    onItemSelect,
    onSearch,
}: ActionMenuProps): React.ReactElement {
    const triggerRef = React.useRef<HTMLButtonElement | null>(null)
    const [query, setQuery] = React.useState('')
    const [openPanel, setOpenPanel] = React.useState<ActionMenuPanel | null>(null)
    const pendingPanelRef = React.useRef<ActionMenuPanel | null>(null)
    const searchedRef = React.useRef(false)
    const results = React.useMemo(() => searchActionMenu(items, query), [items, query])
    const searching = query.trim() !== ''
    // Panels are looked up by id so a re-render with fresh closures shows the latest content.
    const livePanel = openPanel ? (findPanel(items, openPanel.id) ?? openPanel) : null

    const context = React.useMemo<RenderContextValue>(
        () => ({
            fromSearch: searching,
            onItemSelect,
            onSubmenuOpenChange,
            openPanel: (item) => {
                pendingPanelRef.current = item
            },
        }),
        [searching, onItemSelect, onSubmenuOpenChange]
    )

    const changeQuery = (value: string): void => {
        setQuery(value)
        if (value !== '' && !searchedRef.current) {
            searchedRef.current = true
            onSearch?.()
        }
    }

    const menu = (
        <DropdownMenu
            onOpenChange={(open, details) => {
                if (!open && details.reason === 'escape-key' && query !== '') {
                    details.cancel()
                    changeQuery('')
                    return
                }
                if (open) {
                    searchedRef.current = false
                }
                onOpenChange?.(open)
            }}
            onOpenChangeComplete={(open: boolean) => {
                // A panel opens only once the menu has closed and returned focus to the trigger, so the menu's focus
                // return and outside-press handling never reach the popover.
                const pending = pendingPanelRef.current
                if (!open && pending) {
                    pendingPanelRef.current = null
                    setOpenPanel(pending)
                }
            }}
        >
            <DropdownMenuTrigger ref={triggerRef} render={trigger}>
                {triggerChildren}
            </DropdownMenuTrigger>
            <RenderContext.Provider value={context}>
                {searchable ? (
                    // quill caps a flush menu's scroller at 72 spacing units, which shows only a few rows of a long
                    // result list. This cap lets the list grow with the room below the trigger.
                    <DropdownMenuContent align={align} flush className="*:max-h-[min(70dvh,var(--available-height))]">
                        <DropdownMenuInput placeholder={searchPlaceholder} aria-label={searchPlaceholder} />
                        <DropdownMenuList>
                            {searching ? (
                                <SearchResults results={results} emptyLabel={emptyLabel} />
                            ) : (
                                <TopLevel items={items} />
                            )}
                        </DropdownMenuList>
                    </DropdownMenuContent>
                ) : (
                    <DropdownMenuContent align={align}>
                        <TopLevel items={items} />
                    </DropdownMenuContent>
                )}
            </RenderContext.Provider>
        </DropdownMenu>
    )

    return (
        <>
            {searchable ? (
                <DropdownMenuFilterProvider autoHighlight filter={null} value={query} onValueChange={changeQuery}>
                    {menu}
                </DropdownMenuFilterProvider>
            ) : (
                menu
            )}
            <Popover
                open={!!livePanel}
                onOpenChange={(open: boolean) => {
                    if (!open) {
                        setOpenPanel(null)
                    }
                }}
            >
                <PopoverContent
                    anchor={triggerRef}
                    finalFocus={triggerRef}
                    align={align}
                    data-attr={livePanel?.dataAttr ? `${livePanel.dataAttr}-panel` : undefined}
                    className={cn('flex w-80 flex-col gap-2 p-2', livePanel?.panelClassName)}
                >
                    {livePanel?.render()}
                </PopoverContent>
            </Popover>
        </>
    )
}

function findPanel(items: ActionMenuItem[], id: string): ActionMenuPanel | null {
    for (const item of items) {
        if (item.type === 'panel' && item.id === id) {
            return item
        }
        if (item.type === 'submenu') {
            const found = findPanel(item.items, id)
            if (found) {
                return found
            }
        }
    }
    return null
}
