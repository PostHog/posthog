/*
 * Legacy FilterBar compatibility layer.
 *
 * Keep this file for current FilterBar consumers that still use the legacy roots,
 * taxonomicGroupTypes, tokens, FilterChips, and TaxonomicMenuFilter API: Web analytics,
 * marketing analytics, endpoints, customer analytics, and revenue analytics. New filter
 * surfaces should prefer the generic FilterPicker API instead. Do not import this file
 * from FilterPicker; keep the generic picker independent while these consumers migrate.
 */

import { useActions, useValues } from 'kea'
import { ReactElement, ReactNode, useEffect, useMemo, useRef, useState } from 'react'

import {
    IconArrowLeft,
    IconBrackets,
    IconDatabase,
    IconFilter,
    IconHogQL,
    IconPeople,
    IconPerson,
    IconWarning,
} from '@posthog/icons'
import { Button, useCalendar } from '@posthog/quill'

import { DurationPicker } from 'lib/components/DurationPicker/DurationPicker'
import { PropertyFilterBetween } from 'lib/components/PropertyFilters/components/PropertyFilterBetween'
import {
    propertyFilterTypeToPropertyDefinitionType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { dayjs } from 'lib/dayjs'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'
import {
    chooseOperatorMap,
    isOperatorBetween,
    isOperatorDate,
    isOperatorFlag,
    isOperatorMulti,
} from 'lib/utils/operators'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import {
    PropertyDefinitionType,
    PropertyFilterType,
    PropertyFilterValue,
    PropertyOperator,
    PropertyType,
} from '~/types'

import { operatorTokenLabel } from '../FilterPicker/adapters/propertyFilterOperatorAdapter'
import { TaxonomicFilterHeadless, useTaxonomicFilterContext } from '../TaxonomicFilter/headless'
import { useGroupList } from '../TaxonomicFilter/hooks/useGroupList'
import { ExcludedProperties, TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../TaxonomicFilter/types'
import { universalFiltersLogic } from '../UniversalFilters/universalFiltersLogic'
import { FilterTokenPill } from './FilterTokenPill'

/* -------------------------------------------------------------------------- */
/*                                 Node model                                 */
/* -------------------------------------------------------------------------- */

export interface MenuNodeContext {
    /** Close the whole menu — call after committing a filter. */
    close: () => void
}

/**
 * A node in the filter menu. Every menu item is a node. A node is one of:
 *   - a **branch** (`useChildren`): emits child nodes for the current (level-scoped) search query;
 *   - a **panel** (`renderPanel`): renders custom leaf UI (a date/duration/between picker);
 *   - a **leaf** (`onSelect`): commits a filter on click.
 * Branch children are themselves nodes, so the tree recurses to any depth.
 */
export interface MenuNode {
    id: string
    label: string
    icon?: ReactNode
    /** Optional root/menu section label used to group sibling nodes. */
    section?: string
    /** Optional icon shown next to the section label. */
    sectionIcon?: ReactNode
    /** Caption shown on the right (e.g. the source category). */
    hint?: string
    /** Compact label used in the current-path pill. */
    pillLabel?: string
    /** Search placeholder shown while this node is open. */
    searchPlaceholder?: string
    /** Called when this level mounts/open, useful for lazy-loading branch data. */
    onOpen?: () => void
    /** Called when this level's scoped search query changes. */
    onQueryChange?: (query: string) => void
    /** Branch: emits child nodes for `query`. Only invoked for the currently-open node. */
    useChildren?: (query: string) => {
        nodes: MenuNode[]
        isLoading: boolean
        hasMore?: boolean
        loadMore?: () => void
        isLoadingMore?: boolean
    }
    /** Panel: custom leaf UI rendered while this node is open, instead of child nodes. */
    renderPanel?: (ctx: MenuNodeContext) => ReactNode
    /** Inline custom content for stack pages. */
    renderCustom?: ReactNode
    /** Leaf: commit on click. */
    onSelect?: (ctx: MenuNodeContext) => void
}

export interface TaxonomicCategoryNodeConfig {
    kind?: 'taxonomic'
    type: TaxonomicFilterGroupType
    label: string
    icon?: ReactNode
    section?: string
    allowList?: string[]
}

export interface CustomMenuNodeConfig {
    kind: 'node'
    node: MenuNode
}

export type FilterMenuRoot = TaxonomicCategoryNodeConfig | CustomMenuNodeConfig

const isBranch = (node: MenuNode): boolean => !!node.useChildren || !!node.renderPanel

/* -------------------------------------------------------------------------- */
/*                               Navigator shell                              */
/* -------------------------------------------------------------------------- */

const SCROLL_PANEL = 'max-h-[22rem] overflow-y-auto overflow-x-hidden'

/**
 * Recursive node menu rendered as hover-opened flyout sub-menus. Every level (the root content and
 * each sub-menu) has its own search input on top, scoped to that node's children.
 */
export function FilterNodeDropdown({
    node,
    initialPath = [],
    children,
}: {
    node: MenuNode
    initialPath?: MenuNode[]
    children: ReactElement
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const close = (): void => setOpen(false)

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger render={children} />
            <DropdownMenuContent align="start" className="w-[280px]">
                {node.renderPanel ? (
                    node.renderPanel({ close })
                ) : (
                    <NodeLevel node={node} initialPath={initialPath} close={close} />
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export function NodeMenu({
    roots,
    placeholder = 'Filter by property...',
}: {
    roots: MenuNode[]
    placeholder?: string
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const [query, setQuery] = useState('')
    const close = (): void => setOpen(false)

    // A synthetic root whose children are the provided root nodes — makes every level uniform.
    const rootNode = useMemo<MenuNode>(
        () => ({
            id: '__root__',
            label: '',
            searchPlaceholder: placeholder,
            useChildren: (q: string) => {
                const trimmed = q.trim().toLowerCase()
                return {
                    nodes: trimmed ? roots.filter((node) => node.label.toLowerCase().includes(trimmed)) : roots,
                    isLoading: false,
                }
            },
        }),
        [roots, placeholder]
    )

    const [stack, setStack] = useState<MenuNode[]>([rootNode])
    const activeNode = stack[stack.length - 1]

    const breadcrumbParts = stack.filter((node) => node.id !== '__root__').map((node) => node.pillLabel ?? node.label)

    useEffect(() => {
        setStack((currentStack) => {
            if (currentStack.length === 1) {
                return [rootNode]
            }

            const latestRootNodes = rootNode.useChildren?.('')?.nodes ?? []
            const latestActiveNode = latestRootNodes.find((candidate) => candidate.id === currentStack[1].id)
            return [rootNode, latestActiveNode ?? currentStack[1], ...currentStack.slice(2)]
        })
    }, [rootNode])

    const openNode = (nextNode: MenuNode): void => {
        setQuery('')
        setStack((currentStack) => [...currentStack, nextNode])
    }

    const goBack = (): void => {
        setQuery('')
        setStack((currentStack) => currentStack.slice(0, -1))
    }

    const resetMenu = (): void => {
        setQuery('')
        setStack([rootNode])
    }

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger
                render={
                    <div
                        className="flex h-8 min-w-64 items-center gap-1.5 rounded-md px-2 text-sm bg-[var(--color-bg-fill-button-tertiary)] hover:bg-[var(--color-bg-fill-button-tertiary-hover)] border border-transparent"
                        title={placeholder}
                    >
                        <IconFilter className="shrink-0 text-base" />
                        <span className={cn('min-w-0 flex-1 truncate text-left', !query && 'text-tertiary')}>
                            {query || 'Filter'}
                        </span>
                    </div>
                }
            />
            <DropdownMenuContent align="start" className="w-64" sideOffset={-32}>
                <NodeLevelPanel
                    key={activeNode.id}
                    node={activeNode}
                    close={close}
                    query={query}
                    setQuery={setQuery}
                    canGoBack={stack.length > 1}
                    onBack={goBack}
                    onOpen={openNode}
                    onReset={resetMenu}
                    breadcrumbParts={breadcrumbParts}
                    showInlineSearch
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

// One menu panel with explicit drill-down navigation. We intentionally don't use DropdownMenuSub:
// submenu primitives are hover/focus-driven, which makes click-only behavior flaky.
function NodeLevel({
    node,
    initialPath = [],
    close,
}: {
    node: MenuNode
    initialPath?: MenuNode[]
    close: () => void
}): JSX.Element {
    const initialPathKey = `${node.id}:${initialPath.map((pathNode) => pathNode.id).join('/')}`
    const [stack, setStack] = useState<MenuNode[]>([node, ...initialPath])
    const [query, setQuery] = useState('')
    const activeNode = stack[stack.length - 1]

    useEffect(() => {
        setQuery('')
        setStack([node, ...initialPath])
        // Reset only when the requested path actually changes, not on every array identity change.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [initialPathKey])

    const goBack = (): void => {
        setQuery('')
        setStack((currentStack) => currentStack.slice(0, -1))
    }
    const openNode = (nextNode: MenuNode): void => {
        setQuery('')
        setStack((currentStack) => [...currentStack, nextNode])
    }
    const breadcrumbParts = stack
        .filter((stackNode) => stackNode.id !== '__root__')
        .map((stackNode) => stackNode.pillLabel ?? stackNode.label)
    const resetMenu = (): void => {
        setQuery('')
        setStack([node])
    }

    return (
        <NodeLevelPanel
            key={activeNode.id}
            node={activeNode}
            close={close}
            query={query}
            setQuery={setQuery}
            canGoBack={stack.length > 1}
            onBack={goBack}
            onOpen={openNode}
            onReset={resetMenu}
            breadcrumbParts={breadcrumbParts}
            showInlineSearch
        />
    )
}

function NodeLevelPanel({
    node,
    close,
    query,
    setQuery,
    canGoBack,
    onBack,
    onOpen,
    onReset,
    breadcrumbParts,
    showInlineSearch = false,
}: {
    node: MenuNode
    close: () => void
    query: string
    setQuery: (query: string) => void
    canGoBack: boolean
    onBack: () => void
    onOpen: (node: MenuNode) => void
    onReset: () => void
    breadcrumbParts: string[]
    showInlineSearch?: boolean
}): JSX.Element {
    const { nodes, isLoading, hasMore, loadMore, isLoadingMore } = node.useChildren!(query)
    const groupedNodes = useMemo(() => groupNodesBySection(nodes), [nodes])

    useEffect(() => {
        node.onOpen?.()
    }, [node])

    useEffect(() => {
        node.onQueryChange?.(query)
    }, [node, query])

    return (
        <>
            {showInlineSearch && (
                <>
                    <LevelSearchInput
                        value={query}
                        onChange={setQuery}
                        placeholder={node.searchPlaceholder}
                        canGoBack={canGoBack}
                        onBack={onBack}
                    />
                    <DropdownMenuSeparator />
                </>
            )}
            {breadcrumbParts.length > 0 && (
                <div className="flex px-2 pb-1">
                    <FilterTokenPill parts={breadcrumbParts} onRemove={onReset} className="max-w-56" />
                </div>
            )}
            <div
                className={SCROLL_PANEL}
                onScroll={(event) => {
                    const target = event.currentTarget
                    const distanceFromBottom = target.scrollHeight - target.scrollTop - target.clientHeight
                    if (distanceFromBottom < 48 && hasMore && !isLoadingMore) {
                        loadMore?.()
                    }
                }}
            >
                {isLoading && !nodes.length ? (
                    // Plain text, not a (disabled) menu item — Base UI auto-closes a sub-menu whose only
                    // content is a disabled item, so an empty level would otherwise dismiss the flyout.
                    <div className="px-2 py-1.5 text-xs text-tertiary">Loading…</div>
                ) : !nodes.length ? (
                    <div className="px-2 py-1.5 text-xs text-tertiary">No matches</div>
                ) : (
                    <>
                        {groupedNodes.map(({ section, sectionIcon, nodes: sectionNodes }, sectionIndex) => (
                            <div key={section ?? '__ungrouped__'}>
                                {sectionIndex > 0 && <DropdownMenuSeparator />}
                                {section && (
                                    <div className="flex items-center gap-1.5 px-2 py-1.5 text-xs font-semibold text-tertiary [&_svg]:size-3.5">
                                        {sectionIcon}
                                        <span>{section}</span>
                                    </div>
                                )}
                                {sectionNodes.map((child) => (
                                    <NodeItem
                                        key={child.id}
                                        node={child}
                                        close={close}
                                        onOpen={onOpen}
                                        onReset={onReset}
                                    />
                                ))}
                            </div>
                        ))}
                        {isLoadingMore && <div className="px-2 py-1.5 text-xs text-tertiary">Loading more…</div>}
                    </>
                )}
            </div>
        </>
    )
}

function groupNodesBySection(nodes: MenuNode[]): { section?: string; sectionIcon?: ReactNode; nodes: MenuNode[] }[] {
    const groups: { section?: string; sectionIcon?: ReactNode; nodes: MenuNode[] }[] = []

    for (const node of nodes) {
        const lastGroup = groups[groups.length - 1]
        if (lastGroup && lastGroup.section === node.section) {
            lastGroup.nodes.push(node)
        } else {
            groups.push({ section: node.section, sectionIcon: node.sectionIcon, nodes: [node] })
        }
    }

    return groups
}

function NodeItem({
    node,
    close,
    onOpen,
    onReset,
}: {
    node: MenuNode
    close: () => void
    onOpen: (node: MenuNode) => void
    onReset: () => void
}): JSX.Element {
    if (node.renderCustom) {
        return <div className="px-2 py-1.5">{node.renderCustom}</div>
    }

    if (node.renderPanel) {
        return (
            <DropdownMenuItem closeOnClick={false} onClick={() => onOpen(panelNode(node, close))}>
                <span className="truncate">{node.label}</span>
                {node.hint && <span className="ml-auto pl-2 text-xxs uppercase text-tertiary">{node.hint}</span>}
            </DropdownMenuItem>
        )
    }

    if (isBranch(node)) {
        return (
            <DropdownMenuItem closeOnClick={false} onClick={() => onOpen(node)}>
                <span className="truncate">{node.label}</span>
                {node.hint && <span className="ml-auto pl-2 text-xxs uppercase text-tertiary">{node.hint}</span>}
            </DropdownMenuItem>
        )
    }

    return (
        <DropdownMenuItem
            onClick={() =>
                node.onSelect?.({
                    close: () => {
                        onReset()
                        close()
                    },
                })
            }
        >
            <span className="truncate">{node.label}</span>
            {node.hint && <span className="ml-auto pl-2 text-xxs uppercase text-tertiary">{node.hint}</span>}
        </DropdownMenuItem>
    )
}

function panelNode(node: MenuNode, close: () => void): MenuNode {
    return {
        id: `${node.id}:panel`,
        label: node.label,
        searchPlaceholder: node.label,
        useChildren: () => ({
            nodes: [
                {
                    id: `${node.id}:panel-content`,
                    label: node.label,
                    renderCustom: node.renderPanel?.({ close }),
                },
            ],
            isLoading: false,
        }),
    }
}

// Base UI menus move focus to the first item on open (and have no `initialFocus`), so a deferred
// focus on mount re-claims it for the input — fired on every open since the sub-menu mounts lazily.
// `stopPropagation` keeps the menu's typeahead from swallowing typed characters.
function LevelSearchInput({
    value,
    onChange,
    placeholder,
    canGoBack,
    onBack,
}: {
    value: string
    onChange: (v: string) => void
    placeholder?: string
    canGoBack: boolean
    onBack: () => void
}): JSX.Element {
    const inputRef = useRef<HTMLInputElement>(null)

    useEffect(() => {
        const raf = requestAnimationFrame(() => inputRef.current?.focus())
        return () => cancelAnimationFrame(raf)
    }, [])

    return (
        <div className="flex h-8 items-center gap-1.5 rounded-md px-2 text-sm bg-[var(--color-bg-fill-button-tertiary)] border border-transparent">
            {canGoBack ? (
                <button
                    type="button"
                    aria-label="Back"
                    className="shrink-0 text-tertiary hover:text-primary"
                    onClick={(event) => {
                        event.preventDefault()
                        event.stopPropagation()
                        onBack()
                    }}
                >
                    <IconArrowLeft className="text-base" />
                </button>
            ) : (
                <IconFilter aria-hidden className="shrink-0 text-base text-tertiary" />
            )}
            <input
                ref={inputRef}
                type="text"
                aria-label={placeholder ?? 'Search'}
                className="min-w-0 flex-1 border-0 bg-transparent p-0 text-sm outline-none placeholder:text-tertiary"
                placeholder="Filter"
                value={value}
                onChange={(e) => onChange(e.target.value)}
                onKeyDown={(e) => {
                    if (e.key === 'ArrowDown') {
                        // Move into the list so the menu's native roving keyboard navigation takes over.
                        const popup = e.currentTarget.closest(
                            '[data-slot="dropdown-menu-content"],[data-slot="dropdown-menu-sub-content"]'
                        )
                        const firstItem = popup?.querySelector<HTMLElement>('[role="menuitem"]:not([data-disabled])')
                        if (firstItem) {
                            e.preventDefault()
                            // Stop the menu from also advancing (it would skip past the first item).
                            e.stopPropagation()
                            firstItem.focus()
                        }
                        return
                    }
                    // Let dismiss/navigation keys reach the menu; swallow the rest so the menu's
                    // type-ahead doesn't hijack characters meant for the search field.
                    if (!['Escape', 'Tab', 'ArrowUp', 'Enter'].includes(e.key)) {
                        e.stopPropagation()
                    }
                }}
            />
        </div>
    )
}

/* -------------------------------------------------------------------------- */
/*                        Taxonomic node implementation                       */
/* -------------------------------------------------------------------------- */

// Filter types with no operator → value shape: they commit a single filter on click (cohorts, feature
// flags, HogQL). Quick-filter groups have an undefined filter type and are also leaves.
const LEAF_FILTER_TYPES: ReadonlySet<PropertyFilterType> = new Set([
    PropertyFilterType.Cohort,
    PropertyFilterType.HogQL,
    PropertyFilterType.Flag,
])

function taxonomicGroupIcon(groupType: TaxonomicFilterGroupType): ReactNode {
    switch (groupType) {
        case TaxonomicFilterGroupType.PersonProperties:
            return <IconPerson />
        case TaxonomicFilterGroupType.Cohorts:
        case TaxonomicFilterGroupType.CohortsWithAllUsers:
            return <IconPeople />
        case TaxonomicFilterGroupType.HogQLExpression:
            return <IconHogQL />
        case TaxonomicFilterGroupType.ErrorTrackingIssues:
            return <IconWarning />
        case TaxonomicFilterGroupType.DataWarehouse:
        case TaxonomicFilterGroupType.DataWarehouseProperties:
        case TaxonomicFilterGroupType.DataWarehousePersonProperties:
            return <IconDatabase />
        default:
            return <IconBrackets />
    }
}

/** Root nodes (categories) for the taxonomic filter — each drills into properties → operator → value. */
export function useTaxonomicRootNodes(): MenuNode[] {
    const { groups } = useTaxonomicFilterContext()

    return useMemo(
        () =>
            groups
                // Skip meta groups (Recent / Pinned / Suggested) — only real property categories.
                .filter((group) => !group.isMetaGroup)
                .map<MenuNode>((group) => ({
                    id: String(group.type),
                    label: group.name,
                    icon: taxonomicGroupIcon(group.type),
                    searchPlaceholder: `Search ${group.name.toLowerCase()}…`,
                    useChildren(query: string) {
                        return useCategoryChildren(group, query)
                    },
                })),
        [groups]
    )
}

export function useUniversalPropertyFilterNode({
    id,
    label,
    icon,
    filterType,
    propertyKey,
    propertyType,
    eventNames,
}: {
    id: string
    label: string
    icon?: ReactNode
    filterType: PropertyFilterType
    propertyKey: string
    propertyType?: PropertyType
    eventNames?: string[]
}): MenuNode {
    return useMemo(
        () => ({
            id,
            label,
            icon,
            searchPlaceholder: 'Choose an operator…',
            useChildren(operatorQuery: string) {
                return useOperatorChildren(filterType, propertyKey, propertyType, operatorQuery, eventNames)
            },
        }),
        [eventNames, filterType, icon, id, label, propertyKey, propertyType]
    )
}

function useCategoryChildren(
    group: TaxonomicFilterGroup,
    query: string,
    allowList?: string[]
): {
    nodes: MenuNode[]
    isLoading: boolean
    hasMore?: boolean
    loadMore?: () => void
    isLoadingMore?: boolean
} {
    const { getGroupListInput } = useTaxonomicFilterContext()
    const { addGroupFilter } = useActions(universalFiltersLogic)
    const [limit, setLimit] = useState(100)
    const list = useGroupList({ ...getGroupListInput(group), searchQuery: query, limit })

    const nodes = useMemo<MenuNode[]>(
        () =>
            list.items
                .filter((item) => {
                    if (!allowList) {
                        return true
                    }
                    const rawName = group.getName?.(item) ?? (item as { name?: string }).name ?? ''
                    const propertyKey = String(group.getValue?.(item) ?? rawName)
                    return allowList.includes(propertyKey)
                })
                .map((item) => {
                    const rawName = group.getName?.(item) ?? (item as { name?: string }).name ?? ''
                    const label = getCoreFilterDefinition(rawName, group.type)?.label || rawName
                    const propertyKey = String(group.getValue?.(item) ?? rawName)
                    const propertyType = (item as { property_type?: PropertyType }).property_type
                    const icon = group.getIcon?.(item)
                    const filterType = taxonomicFilterTypeToPropertyFilterType(group.type)
                    const canDrill = filterType !== undefined && !LEAF_FILTER_TYPES.has(filterType)

                    // Cohorts / feature flags / HogQL commit directly via the canonical conversion.
                    if (!canDrill) {
                        return {
                            id: `${group.type}:${propertyKey}`,
                            label,
                            icon,
                            onSelect: ({ close }) => {
                                addGroupFilter(group, group.getValue?.(item) ?? null, item as any)
                                close()
                            },
                        }
                    }

                    return {
                        id: `${group.type}:${propertyKey}`,
                        label,
                        icon,
                        searchPlaceholder: 'Choose an operator…',
                        useChildren(operatorQuery: string) {
                            return useOperatorChildren(filterType, propertyKey, propertyType, operatorQuery)
                        },
                    }
                }),
        [group, list.items, allowList, addGroupFilter]
    )

    return {
        nodes,
        isLoading: list.isLoading,
        hasMore: (list.isExpandable && !list.isExpanded) || list.totalResultCount > list.items.length,
        loadMore: () => {
            if (list.isExpandable && !list.isExpanded) {
                list.expand()
            } else {
                setLimit((currentLimit) => currentLimit + 100)
            }
        },
        isLoadingMore: list.isFetching && nodes.length > 0,
    }
}

function useOperatorChildren(
    filterType: PropertyFilterType | undefined,
    propertyKey: string,
    propertyType: PropertyType | undefined,
    query: string,
    eventNames: string[] = []
): {
    nodes: MenuNode[]
    isLoading: boolean
    hasMore?: boolean
    loadMore?: () => void
    isLoadingMore?: boolean
} {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { setGroupValues } = useActions(universalFiltersLogic)
    const { describeProperty } = useValues(propertyDefinitionsModel)

    // The taxonomic item rarely carries `property_type`, so resolve it from the property definitions —
    // this is what picks the type-appropriate operator set (numeric → >,<; string → contains; etc.).
    const definitionType = propertyFilterTypeToPropertyDefinitionType(filterType) ?? PropertyDefinitionType.Event
    const resolvedType = propertyType ?? describeProperty(propertyKey, definitionType) ?? undefined

    const nodes = useMemo<MenuNode[]>(() => {
        const commit = (operator: PropertyOperator, value: PropertyFilterValue, close: () => void): void => {
            if (filterType) {
                setGroupValues([...filterGroup.values, { key: propertyKey, type: filterType, operator, value } as any])
            }
            close()
        }
        const trimmed = query.trim().toLowerCase()

        const operatorNodes = Object.entries(chooseOperatorMap(resolvedType))
            .filter(([, label]) => label.toLowerCase().includes(trimmed))
            .map<MenuNode>(([op, label]) => {
                const operator = op as PropertyOperator

                const symbol = operatorTokenLabel(operator, resolvedType)

                if (isOperatorFlag(operator)) {
                    return { id: op, label, pillLabel: symbol, onSelect: ({ close }) => commit(operator, null, close) }
                }

                if (isOperatorDate(operator)) {
                    return {
                        id: op,
                        label,
                        pillLabel: symbol,
                        renderPanel: ({ close }) => (
                            <DateOperatorPanel
                                operator={operator}
                                onApply={(value) => commit(operator, value, close)}
                            />
                        ),
                    }
                }
                if (isOperatorBetween(operator)) {
                    return {
                        id: op,
                        label,
                        pillLabel: symbol,
                        renderPanel: ({ close }) => (
                            <div className="p-2" onKeyDown={(e) => e.stopPropagation()}>
                                <PropertyFilterBetween
                                    logicKey={propertyKey}
                                    value={null}
                                    onSet={(v) => commit(operator, v ?? null, close)}
                                />
                            </div>
                        ),
                    }
                }
                if (resolvedType === PropertyType.Duration) {
                    return {
                        id: op,
                        label,
                        renderPanel: ({ close }) => (
                            <DurationPanel onPick={(seconds) => commit(operator, seconds, close)} />
                        ),
                    }
                }

                // String / numeric: drill into the property's values (the top search becomes value entry).
                const numeric = resolvedType === PropertyType.Numeric
                return {
                    id: op,
                    label,
                    pillLabel: symbol,
                    searchPlaceholder: numeric ? 'Type a number…' : 'Search or type a value…',
                    useChildren(valueQuery: string) {
                        return useValueChildren(
                            filterType,
                            propertyKey,
                            operator,
                            numeric,
                            valueQuery,
                            (value, close) => commit(operator, value, close),
                            eventNames
                        )
                    },
                }
            })

        if (resolvedType !== PropertyType.DateTime) {
            return operatorNodes
        }

        const shortcutNodes = DATE_TIME_SHORTCUTS.filter((shortcut) =>
            shortcut.label.toLowerCase().includes(trimmed)
        ).map<MenuNode>((shortcut) => ({
            id: `shortcut:${shortcut.id}`,
            label: shortcut.label,
            hint: 'Shortcut',
            onSelect: ({ close }) => commit(PropertyOperator.IsDateAfter, shortcut.value, close),
        }))

        return [...shortcutNodes, ...operatorNodes]
    }, [eventNames, filterType, propertyKey, resolvedType, query, filterGroup.values, setGroupValues])

    return { nodes, isLoading: false }
}

const WEEK_DAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']

const DATE_TIME_SHORTCUTS: { id: string; label: string; value: string }[] = [
    { id: 'last-hour', label: 'Last hour', value: '-1h' },
    { id: 'last-24-hours', label: 'Last 24 hours', value: '-24h' },
    { id: 'last-2-days', label: 'Last 2 days', value: '-2d' },
    { id: 'last-7-days', label: 'Last 7 days', value: '-7d' },
    { id: 'last-30-days', label: 'Last 30 days', value: '-30d' },
]

export function SingleDatePickerPanel({ onSelect }: { onSelect: (value: string) => void }): JSX.Element {
    const { calendar, viewing, viewPreviousMonth, viewNextMonth } = useCalendar({ viewing: new Date() })

    return (
        <div className="w-64 p-2" onKeyDown={(e) => e.stopPropagation()}>
            <div className="mb-2 flex items-center justify-between gap-2">
                <Button size="icon-sm" variant="default" onClick={viewPreviousMonth} aria-label="Previous month">
                    <IconArrowLeft />
                </Button>
                <span className="text-sm font-medium">{dayjs(viewing).format('MMMM YYYY')}</span>
                <Button size="icon-sm" variant="default" onClick={viewNextMonth} aria-label="Next month">
                    <IconArrowLeft className="rotate-180" />
                </Button>
            </div>
            <div className="grid grid-cols-7 gap-1 text-center text-xs text-tertiary">
                {WEEK_DAYS.map((day) => (
                    <div key={day}>{day}</div>
                ))}
            </div>
            {calendar[0].map((week) => (
                <div key={week[0].toISOString()} className="mt-1 grid grid-cols-7 gap-1">
                    {week.map((day) => {
                        const isCurrentMonth = day.getMonth() === viewing.getMonth()
                        return (
                            <Button
                                key={day.toISOString()}
                                size="icon-sm"
                                variant="default"
                                className={cn('tabular-nums', !isCurrentMonth && 'opacity-30')}
                                onClick={() => onSelect(dayjs(day).format('YYYY-MM-DD'))}
                            >
                                {day.getDate()}
                            </Button>
                        )
                    })}
                </div>
            ))}
        </div>
    )
}

function DateOperatorPanel({
    onApply,
}: {
    operator: PropertyOperator
    onApply: (value: PropertyFilterValue) => void
}): JSX.Element {
    return <SingleDatePickerPanel onSelect={onApply} />
}

function useValueChildren(
    filterType: PropertyFilterType | undefined,
    propertyKey: string,
    operator: PropertyOperator,
    numeric: boolean,
    query: string,
    commit: (value: PropertyFilterValue, close: () => void) => void,
    eventNames: string[] = []
): { nodes: MenuNode[]; isLoading: boolean } {
    const definitionType = propertyFilterTypeToPropertyDefinitionType(filterType) ?? PropertyDefinitionType.Event
    const { options, formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const propertyOption = options[propertyKey]

    const trimmed = numeric ? query.replace(/[^0-9.-]/g, '').trim() : query.trim()

    useEffect(() => {
        // Debounced + abort-stale inside the model, so calling on each keystroke is safe.
        loadPropertyValues({
            endpoint: undefined,
            type: definitionType,
            newInput: trimmed || undefined,
            propertyKey,
            eventNames,
        })
    }, [loadPropertyValues, definitionType, propertyKey, trimmed, eventNames])

    const nodes = useMemo<MenuNode[]>(() => {
        const finalValue = (raw: string | number): PropertyFilterValue => (isOperatorMulti(operator) ? [raw] : raw)
        const values = propertyOption?.values ?? []
        const result: MenuNode[] = []

        // Free-text / custom value when it isn't already an exact known value.
        if (trimmed && !values.some((value) => String(value.name) === trimmed)) {
            result.push({
                id: '__use__',
                label: `Use “${trimmed}”`,
                onSelect: ({ close }) => commit(finalValue(numeric ? Number(trimmed) : trimmed), close),
            })
        }
        values.forEach((value, index) => {
            result.push({
                id: `value-${index}`,
                label: String(formatPropertyValueForDisplay(propertyKey, value.name, definitionType)),
                onSelect: ({ close }) => commit(finalValue(numeric ? Number(value.name) : String(value.name)), close),
            })
        })
        return result
    }, [
        propertyOption?.values,
        trimmed,
        numeric,
        operator,
        propertyKey,
        definitionType,
        formatPropertyValueForDisplay,
        commit,
    ])

    return { nodes, isLoading: propertyOption?.status === 'loading' && !(propertyOption?.values?.length ?? 0) }
}

// Duration values: the standard picker plus an Apply row (it has no commit affordance itself).
function DurationPanel({ onPick }: { onPick: (seconds: number) => void }): JSX.Element {
    const [seconds, setSeconds] = useState(0)
    return (
        <div className="flex flex-col gap-2 p-2" onKeyDown={(e) => e.stopPropagation()}>
            <DurationPicker autoFocus value={seconds} onChange={setSeconds} />
            <DropdownMenuItem onClick={() => onPick(seconds)}>Apply</DropdownMenuItem>
        </div>
    )
}

/* -------------------------------------------------------------------------- */
/*                                   Wrapper                                   */
/* -------------------------------------------------------------------------- */

/**
 * Node menu wired to the taxonomic filter: mounts the headless root, builds taxonomic root nodes, and
 * prepends any `extraRoots`. Selections commit into the surrounding `universalFiltersLogic`.
 */
export function TaxonomicMenuFilter({
    taxonomicGroupTypes,
    roots,
    excludedProperties,
    includeTaxonomicCategories = true,
}: {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    /** Ordered product-specific roots shown before optional default taxonomic categories. */
    roots?: FilterMenuRoot[]
    /** Properties to hide from a taxonomic group (e.g. an `assignee` handled by a custom node). */
    excludedProperties?: ExcludedProperties
    includeTaxonomicCategories?: boolean
}): JSX.Element {
    return (
        <TaxonomicFilterHeadless.Root
            className="contents"
            bindRootProps={false}
            taxonomicGroupTypes={taxonomicGroupTypes}
            excludedProperties={excludedProperties}
            onChange={() => {}}
        >
            <TaxonomicNodeMenu roots={roots} includeTaxonomicCategories={includeTaxonomicCategories} />
        </TaxonomicFilterHeadless.Root>
    )
}

function TaxonomicNodeMenu({
    roots = [],
    includeTaxonomicCategories,
}: {
    roots?: FilterMenuRoot[]
    includeTaxonomicCategories: boolean
}): JSX.Element {
    const { groups } = useTaxonomicFilterContext()
    const taxonomicRoots = useTaxonomicRootNodes()
    const productRoots = useMemo<MenuNode[]>(
        () =>
            roots.flatMap((root) => {
                if ('node' in root) {
                    return [root.node]
                }
                const config = root
                const group = groups.find((candidate) => candidate.type === config.type)
                if (!group) {
                    return []
                }
                return [
                    {
                        id: String(config.type),
                        label: config.label,
                        icon: config.icon ?? taxonomicGroupIcon(config.type),
                        section: config.section,
                        searchPlaceholder: `Search ${config.label.toLowerCase()}…`,
                        useChildren(query: string) {
                            return useCategoryChildren(group, query, config.allowList)
                        },
                    },
                ]
            }),
        [groups, roots]
    )
    return <NodeMenu roots={[...productRoots, ...(includeTaxonomicCategories ? taxonomicRoots : [])]} />
}
