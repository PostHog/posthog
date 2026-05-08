/**
 * Composable TaxonomicFilter autocomplete (Base UI Autocomplete + Quill
 * primitives). Every piece is opt-in — `Root` is a pure provider; the
 * Popover, Trigger, Content, Input, Chips, List are sibling primitives the
 * consumer composes in any order.
 *
 *   <TaxonomicAutocomplete.Root>
 *     <TaxonomicAutocomplete.Popover>
 *       <TaxonomicAutocomplete.Trigger />
 *       <TaxonomicAutocomplete.Content>
 *         <TaxonomicAutocomplete.Input />
 *         <TaxonomicAutocomplete.Chips />
 *         <TaxonomicAutocomplete.List />
 *       </TaxonomicAutocomplete.Content>
 *     </TaxonomicAutocomplete.Popover>
 *   </TaxonomicAutocomplete.Root>
 *
 * Or wire raw Quill primitives via `useTaxonomicAutocomplete()` if you
 * need full control over the popover (or want to render inline, in a
 * Sheet, etc).
 *
 * Selecting any row closes the popover. Pass `open` + `onOpenChange` to
 * control externally.
 *
 * Modes:
 *   - 'all'  — merges items from every visible group, single Fuse pass.
 *              Selecting routes back to the source group.
 *   - <type> — only that group's items.
 *
 * For both modes, every visible group is fetched via `useGroupList` while
 * the popover is open so 'All' search has data ready.
 */
import { Autocomplete } from '@base-ui/react/autocomplete'
import { useActions, useValues } from 'kea'
import {
    createContext,
    ReactElement,
    ReactNode,
    RefObject,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
    useState,
} from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { IconChevronRight } from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    cn,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    InputGroup,
    InputGroupInput,
    Popover,
    PopoverContent,
    PopoverTrigger,
    ScrollArea,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { createFuse } from 'lib/utils/fuseSearch'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { PropertyDefinitionType } from '~/types'

import { useGroupList } from '../hooks/useGroupList'
import { hasPinnedContext, taxonomicFilterPinnedPropertiesLogic } from '../taxonomicFilterPinnedPropertiesLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from '../types'
import { useTaxonomicFilterContext } from './context'

export type TaxonomicAutocompleteCategoryMode = 'all' | TaxonomicFilterGroupType

export interface TaxonomicAutocompleteCategory {
    /** 'all' for the synthetic "all" entry, otherwise the group type. */
    id: TaxonomicAutocompleteCategoryMode
    /** Human label — `group.name` for groups, "All" for the synthetic entry. */
    name: string
    isActive: boolean
    onSelect: () => void
    /** Underlying group, undefined for the 'all' entry. */
    group?: TaxonomicFilterGroup
    /** Number of items currently loaded for the group. Undefined for 'all'. */
    count?: number
    isLoading?: boolean
    needsMoreSearchCharacters?: boolean
}

export interface TaxonomicAutocompleteEntry {
    item: TaxonomicDefinitionTypes
    group: TaxonomicFilterGroup
    name: string
    friendlyLabel?: string
}

/**
 * Lightweight seed for `defaultSelected` — consumer doesn't need to know
 * the full `TaxonomicFilterGroup` config, just the type. Resolved to a
 * full `TaxonomicAutocompleteEntry` once Root has the matching group.
 */
export interface TaxonomicAutocompleteSeed {
    groupType: TaxonomicFilterGroupType
    /** Underlying value (e.g. `"$pageview"`). Used for value-based matching. */
    value: TaxonomicFilterValue
    /** Raw name (e.g. `"$pageview"`). */
    name: string
    /** Friendly label (e.g. `"Pageview"`). Falls back to `name` for the trigger. */
    friendlyLabel?: string
}

type IndexedItem = TaxonomicAutocompleteEntry

/**
 * Sub-page kinds in the popover view stack. `configure` = inline form
 * before commit (DWH columns, HogQL editor). `details` = read-only
 * metadata sheet (description, type, sent-as, pin / edit / open buttons).
 *
 * Both render via the shared `Header` + sliding view stack; the only
 * difference is which `<…View>` primitive matches the active kind.
 */
export type TaxonomicAutocompletePageKind = 'configure' | 'details'

export interface TaxonomicAutocompletePage {
    kind: TaxonomicAutocompletePageKind
    entry: TaxonomicAutocompleteEntry
}

/**
 * Curation meta groups — user shortcuts (Recent / Pinned / Suggested).
 * These get auto-injected by the orchestrator but live as separate UX
 * affordances elsewhere; we hide them from the chip row + 'all' search.
 *
 * Distinct from the orchestrator's broader `META_GROUP_TYPES` set, which
 * also includes render-driven groups like `HogQLExpression` and
 * `Wildcards` — those ARE first-class chips here.
 */
const CURATION_META_GROUP_TYPES: ReadonlySet<TaxonomicFilterGroupType> = new Set([
    TaxonomicFilterGroupType.SuggestedFilters,
    TaxonomicFilterGroupType.RecentFilters,
    TaxonomicFilterGroupType.PinnedFilters,
])

interface AutocompleteCtx {
    category: TaxonomicAutocompleteCategoryMode
    setCategory: (m: TaxonomicAutocompleteCategoryMode) => void
    visibleGroups: TaxonomicFilterGroup[]
    targetGroups: TaxonomicFilterGroup[]
    searchQuery: string
    setSearchQuery: (q: string) => void
    items: IndexedItem[]
    inputPlaceholder?: string
    listClassName?: string
    maxItems: number
    open: boolean
    setOpen: (v: boolean) => void
    onSelectEntry: (entry: IndexedItem) => void
    itemsByType: Record<string, TaxonomicDefinitionTypes[]>
    loadingByType: Record<string, boolean>
    needsMoreByType: Record<string, boolean>
    emptyState: ReactNode
    /** Last entry selected through this UI (rich data: group + item + labels). */
    selectedEntry: IndexedItem | null
    clearSelection: () => void
    /** Currently keyboard/pointer-highlighted row (transient — reset on close). */
    highlightedEntry: IndexedItem | null
    setHighlightedEntry: (entry: IndexedItem | null) => void
    /** Currently controlled value from the orchestrator (raw, no item context). */
    value: TaxonomicFilterValue | undefined
    /** Ref to the search input — Input attaches it on mount. */
    inputRef: RefObject<HTMLInputElement | null>
    /** Move focus to the search input. */
    focusInput: () => void
    /** Label for the default Trigger button when no entry is selected. */
    triggerLabel?: string
    /** Active sub-page on the view stack, or null in the root view. */
    pendingPage: TaxonomicAutocompletePage | null
    /** Convenience: `pendingPage?.entry ?? null`. */
    pendingEntry: IndexedItem | null
    /** Group types that have a `<ConfigureView>` registered. */
    configuredTypes: ReadonlySet<TaxonomicFilterGroupType>
    addConfiguredType: (t: TaxonomicFilterGroupType) => void
    removeConfiguredType: (t: TaxonomicFilterGroupType) => void
    /** Group types that have a `<DetailsView>` registered. */
    detailsTypes: ReadonlySet<TaxonomicFilterGroupType>
    addDetailsType: (t: TaxonomicFilterGroupType) => void
    removeDetailsType: (t: TaxonomicFilterGroupType) => void
    /**
     * Group types managed by `<MenuTrigger>` shortcuts — excluded from
     * popover chips + list so they only surface in the dropdown menu.
     */
    dropdownManagedTypes: ReadonlySet<TaxonomicFilterGroupType>
    addDropdownManagedType: (t: TaxonomicFilterGroupType) => void
    removeDropdownManagedType: (t: TaxonomicFilterGroupType) => void
    /** True while a `<MenuTrigger>` is mounted. */
    hasMenuTrigger: boolean
    setHasMenuTrigger: (v: boolean) => void
    /**
     * Ref to the trigger button when `<MenuTrigger>` is in use — Content
     * uses this as the popover anchor instead of `<PopoverTrigger>`. Lets
     * the menu and popover share the same visible button without their
     * click handlers fighting each other.
     */
    triggerRef: RefObject<HTMLElement | null>
    /** Open the configurator for an entry (e.g. clicking the item segment of SegmentedTrigger). */
    openConfigureFor: (entry: IndexedItem) => void
    /** Open the details sheet for an entry (e.g. arrow-right → View cell). */
    openDetailsFor: (entry: IndexedItem) => void
    /** Commit the pending entry, optionally merging extra fields into the item. */
    commitPending: (extra?: Record<string, unknown>) => void
    /** Cancel the pending sub-view, leaving any prior selection intact. */
    cancelPending: () => void
    /** Title for the active sub-view; pushed up by the sub-view for `Header`. */
    pendingTitle: ReactNode | null
    setPendingTitle: (t: ReactNode | null) => void
}

const Ctx = createContext<AutocompleteCtx | null>(null)

function useAutocompleteCtx(): AutocompleteCtx {
    const ctx = useContext(Ctx)
    if (!ctx) {
        throw new Error('TaxonomicAutocomplete sub-components must be used inside <TaxonomicAutocomplete.Root>.')
    }
    return ctx
}

// `threshold` + `ignoreDiacritics` come from `createFuse` defaults; we
// only override the keys + the `ignoreLocation` switch here.
const FUSE_OPTIONS = {
    keys: ['name', 'friendlyLabel'],
    ignoreLocation: true,
}

function getRawName(item: TaxonomicDefinitionTypes, group: TaxonomicFilterGroup): string {
    return (
        group.getName?.(item) ??
        ('name' in (item as unknown as Record<string, unknown>)
            ? ((item as unknown as { name?: string }).name ?? '')
            : '') ??
        ''
    )
}

function getFriendlyLabel(item: TaxonomicDefinitionTypes, group: TaxonomicFilterGroup): string | undefined {
    const raw = getRawName(item, group)
    if (!raw) {
        return undefined
    }
    return getCoreFilterDefinition(raw, group.type)?.label
}

// Autocomplete owns these keys; stop them from bubbling into the
// orchestrator's `rootProps.onKeyDown`, which would call useGroupList's
// moveUp/moveDown/selectSelected and double-handle the event (and worse,
// preventDefault arrow keys before Autocomplete sees them). Tab still
// bubbles so the parent's tabLeft/tabRight tab-switching keeps working.
function stopOwnedKeys(e: React.KeyboardEvent<HTMLDivElement>): void {
    switch (e.key) {
        case 'ArrowUp':
        case 'ArrowDown':
        case 'Home':
        case 'End':
        case 'PageUp':
        case 'PageDown':
        case 'Enter':
        case 'Escape':
            e.stopPropagation()
            break
    }
}

export interface TaxonomicAutocompleteRootProps {
    children: ReactNode
    /** Controlled open state. */
    open?: boolean
    onOpenChange?: (open: boolean) => void
    /** Uncontrolled initial open. */
    defaultOpen?: boolean
    /** Default category. Defaults to 'all'. */
    defaultCategory?: TaxonomicAutocompleteCategoryMode
    /** Hide meta groups (Suggested / Recent / Pinned) from categories + 'all' search. Default true. */
    excludeMetaFromAll?: boolean
    /** Maximum items rendered in the list. Default 50. */
    maxItems?: number
    listClassName?: string
    /** Override the search input placeholder. */
    placeholder?: string
    /**
     * Label shown by the default Trigger button when nothing is selected.
     * Independent of `placeholder` (which is for the search input only).
     * Falls back to `placeholder`, then `"Search…"`.
     */
    triggerLabel?: string
    /**
     * Pre-fill the trigger with an initial selection on mount. Uncontrolled
     * — only seeds once, after that the user's selections take over.
     */
    defaultSelected?: TaxonomicAutocompleteSeed | null
}

export function Root({
    children,
    open,
    onOpenChange,
    defaultOpen,
    defaultCategory = 'all',
    excludeMetaFromAll = true,
    maxItems = 50,
    listClassName,
    placeholder,
    triggerLabel,
    defaultSelected,
}: TaxonomicAutocompleteRootProps): JSX.Element | null {
    const { groups, inputProps, selectItem, searchQuery, setSearchQuery, value } = useTaxonomicFilterContext()
    const [internalOpen, setInternalOpen] = useState<boolean>(defaultOpen ?? false)
    const [category, setCategory] = useState<TaxonomicAutocompleteCategoryMode>(defaultCategory)
    const [itemsByType, setItemsByType] = useState<Record<string, TaxonomicDefinitionTypes[]>>({})
    const [loadingByType, setLoadingByType] = useState<Record<string, boolean>>({})
    const [needsMoreByType, setNeedsMoreByType] = useState<Record<string, boolean>>({})
    const [selectedEntry, setSelectedEntry] = useState<IndexedItem | null>(null)
    // Transient — base-ui's `onItemHighlighted` writes here so consumers
    // can render side panels (preview, hover details) keyed off the
    // currently-cursored row without DOM-walking.
    const [highlightedEntry, setHighlightedEntry] = useState<IndexedItem | null>(null)
    const [pendingPage, setPendingPage] = useState<TaxonomicAutocompletePage | null>(null)
    const [pendingTitle, setPendingTitle] = useState<ReactNode | null>(null)
    const [configuredTypes, setConfiguredTypes] = useState<Set<TaxonomicFilterGroupType>>(() => new Set())
    const [detailsTypes, setDetailsTypes] = useState<Set<TaxonomicFilterGroupType>>(() => new Set())
    const [dropdownManagedTypes, setDropdownManagedTypes] = useState<Set<TaxonomicFilterGroupType>>(() => new Set())
    const [hasMenuTrigger, setHasMenuTrigger] = useState(false)
    const triggerRef = useRef<HTMLElement | null>(null)
    const seededRef = useRef(false)
    const inputRef = useRef<HTMLInputElement | null>(null)
    const focusInput = useCallback((): void => {
        inputRef.current?.focus()
    }, [])

    const addConfiguredType = useCallback((t: TaxonomicFilterGroupType): void => {
        setConfiguredTypes((prev) => {
            if (prev.has(t)) {
                return prev
            }
            const next = new Set(prev)
            next.add(t)
            return next
        })
    }, [])
    const removeConfiguredType = useCallback((t: TaxonomicFilterGroupType): void => {
        setConfiguredTypes((prev) => {
            if (!prev.has(t)) {
                return prev
            }
            const next = new Set(prev)
            next.delete(t)
            return next
        })
    }, [])
    const addDetailsType = useCallback((t: TaxonomicFilterGroupType): void => {
        setDetailsTypes((prev) => {
            if (prev.has(t)) {
                return prev
            }
            const next = new Set(prev)
            next.add(t)
            return next
        })
    }, [])
    const removeDetailsType = useCallback((t: TaxonomicFilterGroupType): void => {
        setDetailsTypes((prev) => {
            if (!prev.has(t)) {
                return prev
            }
            const next = new Set(prev)
            next.delete(t)
            return next
        })
    }, [])
    const addDropdownManagedType = useCallback((t: TaxonomicFilterGroupType): void => {
        setDropdownManagedTypes((prev) => {
            if (prev.has(t)) {
                return prev
            }
            const next = new Set(prev)
            next.add(t)
            return next
        })
    }, [])
    const removeDropdownManagedType = useCallback((t: TaxonomicFilterGroupType): void => {
        setDropdownManagedTypes((prev) => {
            if (!prev.has(t)) {
                return prev
            }
            const next = new Set(prev)
            next.delete(t)
            return next
        })
    }, [])

    const isControlled = open !== undefined
    const isOpen = isControlled ? open : internalOpen
    const setOpen = useCallback(
        (v: boolean): void => {
            if (!isControlled) {
                setInternalOpen(v)
            }
            // Reset transient highlight when the popover closes — the
            // next open should start fresh rather than echo a stale row.
            if (!v) {
                setHighlightedEntry(null)
            }
            onOpenChange?.(v)
        },
        [isControlled, onOpenChange]
    )

    const visibleGroups = useMemo(
        // Exclude *curation* meta (Recent / Pinned / Suggested) — those
        // exist as user shortcuts elsewhere. Also exclude any types
        // registered as `dropdownManagedTypes` by `<MenuTrigger>` (DWH /
        // HogQL surfaced as menu shortcuts, not chips).
        () => {
            const hidden = new Set<TaxonomicFilterGroupType>()
            if (excludeMetaFromAll) {
                CURATION_META_GROUP_TYPES.forEach((t) => hidden.add(t))
            }
            dropdownManagedTypes.forEach((t) => hidden.add(t))
            return hidden.size > 0 ? groups.filter((g) => !hidden.has(g.type)) : groups
        },
        [groups, excludeMetaFromAll, dropdownManagedTypes]
    )

    // Resolve `defaultSelected` once a matching group is available. Single
    // shot — subsequent prop changes don't re-seed (treat it as defaultValue).
    useEffect(() => {
        if (seededRef.current || !defaultSelected || groups.length === 0) {
            return
        }
        const grp = groups.find((g) => g.type === defaultSelected.groupType)
        if (!grp) {
            return
        }
        seededRef.current = true
        // Synthetic item — `getValue`/`getName` use whatever the group
        // accessors expect; we only need this to round-trip the trigger
        // label and the controlled-value comparison. Once the user clicks
        // a real row, this gets replaced with a fully-formed entry.
        const syntheticItem = {
            name: defaultSelected.name,
            value: defaultSelected.value,
        } as unknown as TaxonomicDefinitionTypes
        setSelectedEntry({
            item: syntheticItem,
            group: grp,
            name: defaultSelected.name,
            friendlyLabel: defaultSelected.friendlyLabel,
        })
    }, [defaultSelected, groups])

    const targetGroups = useMemo(
        () => (category === 'all' ? visibleGroups : visibleGroups.filter((g) => g.type === category)),
        [visibleGroups, category]
    )

    const indexed = useMemo<IndexedItem[]>(() => {
        const merged: IndexedItem[] = []
        for (const group of targetGroups) {
            const items = itemsByType[group.type] ?? []
            // Render-driven groups (e.g. `HogQLExpression` with InlineHogQLEditor)
            // have no list items — they're a single editor surface. Synthesise
            // one sentinel row so the user has something to click; selection
            // hands off to a `<ConfigureView>` registered for that group.
            if (items.length === 0 && (group as { render?: unknown }).render) {
                merged.push({
                    item: { name: group.name } as TaxonomicDefinitionTypes,
                    group,
                    name: group.name,
                    friendlyLabel: undefined,
                })
                continue
            }
            for (const item of items) {
                merged.push({
                    item,
                    group,
                    name: getRawName(item, group),
                    friendlyLabel: getFriendlyLabel(item, group),
                })
            }
        }
        return merged
    }, [targetGroups, itemsByType])

    const filtered = useMemo<IndexedItem[]>(() => {
        const trimmed = searchQuery.trim()
        if (!trimmed) {
            return indexed
        }
        const fuse = createFuse(indexed, FUSE_OPTIONS as Parameters<typeof createFuse<IndexedItem>>[1])
        return fuse.search(trimmed).map((r) => r.item)
    }, [indexed, searchQuery])

    const items = useMemo(() => filtered.slice(0, maxItems), [filtered, maxItems])

    const anyLoading = targetGroups.some((g) => loadingByType[g.type])
    const allNeedMore = targetGroups.length > 0 && targetGroups.every((g) => needsMoreByType[g.type])
    const emptyState: ReactNode = allNeedMore ? 'Type more to search' : anyLoading ? 'Loading…' : 'No matches'

    const commitEntry = useCallback(
        (entry: IndexedItem, extra?: Record<string, unknown>): void => {
            const mergedItem = extra
                ? ({ ...(entry.item as object), ...extra } as unknown as TaxonomicDefinitionTypes)
                : entry.item
            const itemValue = entry.group.getValue?.(mergedItem) ?? null
            const finalEntry: IndexedItem = extra ? { ...entry, item: mergedItem } : entry
            setSelectedEntry(finalEntry)
            selectItem(entry.group, itemValue, mergedItem)
            setOpen(false)
        },
        [selectItem, setOpen]
    )

    const onSelectEntry = useCallback(
        (entry: IndexedItem): void => {
            // Two-phase: if a `<ConfigureView>` is registered for this
            // group, defer commit until the form completes. Otherwise
            // commit immediately.
            if (configuredTypes.has(entry.group.type)) {
                setPendingPage({ kind: 'configure', entry })
                return
            }
            commitEntry(entry)
        },
        [commitEntry, configuredTypes]
    )

    const openConfigureFor = useCallback((entry: IndexedItem): void => {
        setPendingPage({ kind: 'configure', entry })
    }, [])

    const openDetailsFor = useCallback((entry: IndexedItem): void => {
        setPendingPage({ kind: 'details', entry })
    }, [])

    const commitPending = useCallback(
        (extra?: Record<string, unknown>): void => {
            const entry = pendingPage?.entry
            if (entry) {
                commitEntry(entry, extra)
                setPendingPage(null)
            }
        },
        [pendingPage, commitEntry]
    )

    const cancelPending = useCallback((): void => {
        setPendingPage(null)
    }, [])

    const pendingEntry = pendingPage?.entry ?? null

    // When a sub-view closes (pendingPage → null), refocus the search input
    // so the next Escape lands on Input's handler — which closes the
    // popover — instead of dying on the unmounted form field. This is what
    // makes "Esc, Esc" feel like "back, then close" once a sub-view is open.
    //
    // RootView (and its Input) was unmounted during the sub-view, so wait
    // for the next paint before focusing — `inputRef.current` is set during
    // the commit, but base-ui's Autocomplete.Input wraps render-prop refs
    // through useRender, and the ref attachment can land a tick after the
    // outer commit. `setTimeout(0)` is a reliable post-commit hook.
    const prevPendingRef = useRef<TaxonomicAutocompletePage | null>(pendingPage)
    useEffect(() => {
        if (prevPendingRef.current && !pendingPage) {
            const t = window.setTimeout(() => inputRef.current?.focus(), 0)
            prevPendingRef.current = pendingPage
            return () => window.clearTimeout(t)
        }
        prevPendingRef.current = pendingPage
        return undefined
    }, [pendingPage])

    const clearSelection = useCallback(() => setSelectedEntry(null), [])

    // If the consumer is *explicitly* controlling `value` and clears it
    // (null) or sets it to something that doesn't match the cached entry,
    // drop the cache so the trigger doesn't lie. `undefined` means
    // uncontrolled — don't touch the cache, otherwise we'd race with our
    // own `setSelectedEntry` on click.
    useEffect(() => {
        if (value === undefined) {
            return
        }
        if (value === null) {
            setSelectedEntry(null)
            return
        }
        if (selectedEntry) {
            const currentValue = selectedEntry.group.getValue?.(selectedEntry.item)
            if (currentValue !== value) {
                setSelectedEntry(null)
            }
        }
    }, [value, selectedEntry])

    const ctxValue = useMemo<AutocompleteCtx>(
        () => ({
            category,
            setCategory,
            visibleGroups,
            targetGroups,
            searchQuery,
            setSearchQuery,
            items,
            inputPlaceholder: placeholder ?? inputProps.placeholder,
            listClassName,
            maxItems,
            open: isOpen,
            setOpen,
            onSelectEntry,
            itemsByType,
            loadingByType,
            needsMoreByType,
            emptyState,
            selectedEntry,
            clearSelection,
            highlightedEntry,
            setHighlightedEntry,
            value,
            inputRef,
            focusInput,
            triggerLabel,
            pendingPage,
            pendingEntry,
            configuredTypes,
            addConfiguredType,
            removeConfiguredType,
            detailsTypes,
            addDetailsType,
            removeDetailsType,
            dropdownManagedTypes,
            addDropdownManagedType,
            removeDropdownManagedType,
            hasMenuTrigger,
            setHasMenuTrigger,
            triggerRef,
            openConfigureFor,
            openDetailsFor,
            commitPending,
            cancelPending,
            pendingTitle,
            setPendingTitle,
        }),
        [
            category,
            visibleGroups,
            targetGroups,
            searchQuery,
            setSearchQuery,
            items,
            placeholder,
            inputProps.placeholder,
            listClassName,
            maxItems,
            isOpen,
            setOpen,
            onSelectEntry,
            itemsByType,
            loadingByType,
            needsMoreByType,
            emptyState,
            selectedEntry,
            clearSelection,
            highlightedEntry,
            value,
            focusInput,
            triggerLabel,
            pendingPage,
            pendingEntry,
            configuredTypes,
            addConfiguredType,
            removeConfiguredType,
            detailsTypes,
            addDetailsType,
            removeDetailsType,
            dropdownManagedTypes,
            addDropdownManagedType,
            removeDropdownManagedType,
            hasMenuTrigger,
            openConfigureFor,
            openDetailsFor,
            commitPending,
            cancelPending,
            pendingTitle,
        ]
    )

    const reportItems = useCallback(
        (type: string, next: TaxonomicDefinitionTypes[]): void =>
            setItemsByType((prev) => (prev[type] === next ? prev : { ...prev, [type]: next })),
        []
    )
    const reportLoading = useCallback(
        (type: string, loading: boolean): void =>
            setLoadingByType((prev) => (prev[type] === loading ? prev : { ...prev, [type]: loading })),
        []
    )
    const reportNeedsMore = useCallback(
        (type: string, needs: boolean): void =>
            setNeedsMoreByType((prev) => (prev[type] === needs ? prev : { ...prev, [type]: needs })),
        []
    )

    if (groups.length === 0) {
        return null
    }

    return (
        <Ctx.Provider value={ctxValue}>
            {/* Fetchers run while the popover is open so 'All' search has
                every group's items ready, and so the categories list can
                expose live counts via `useTaxonomicAutocompleteCategories`.
                Zero-DOM components — render anywhere in the tree. */}
            {isOpen &&
                visibleGroups.map((group) => (
                    <GroupItemsFetcher
                        key={group.type}
                        group={group}
                        onItems={reportItems}
                        onLoading={reportLoading}
                        onNeedsMore={reportNeedsMore}
                    />
                ))}
            {children}
        </Ctx.Provider>
    )
}

/**
 * Quill Popover wrapper bound to Root state. Optional — drop in a raw
 * `<Popover open={...} onOpenChange={...}>` instead if you need to swap
 * the container (Sheet, inline panel, etc.). Use `useTaxonomicAutocomplete()`
 * to read the open state for that case.
 *
 * Sub-views (DataWarehouse field config, HogQL editor, etc.) render inside
 * this same popover via `<RootView>` + `<ConfigureView>` — no nested
 * dialogs, just an internal view stack with back-button + Esc-to-go-back.
 */
function PopoverWrapper({ children }: { children: ReactNode }): JSX.Element {
    const ctx = useAutocompleteCtx()
    return (
        <Popover
            open={ctx.open}
            onOpenChange={(open, details) => {
                // When MenuTrigger is mounted, the popover trigger and the
                // dropdown-menu trigger live on the same button. Pressing
                // it should open the MENU only — `trigger-press` opens
                // here are dropped. Programmatic opens (menu items calling
                // ctx.setOpen) come through with reason='none' and pass.
                if (
                    open &&
                    ctx.hasMenuTrigger &&
                    (details?.reason === 'trigger-press' || details?.reason === 'trigger-hover')
                ) {
                    return
                }
                ctx.setOpen(open)
            }}
        >
            {children}
        </Popover>
    )
}

interface GroupItemsFetcherProps {
    group: TaxonomicFilterGroup
    onItems: (type: string, items: TaxonomicDefinitionTypes[]) => void
    onLoading: (type: string, loading: boolean) => void
    onNeedsMore: (type: string, needs: boolean) => void
}

function GroupItemsFetcher({ group, onItems, onLoading, onNeedsMore }: GroupItemsFetcherProps): null {
    const { getGroupListInput } = useTaxonomicFilterContext()
    const list = useGroupList(getGroupListInput(group))
    useEffect(() => {
        onItems(group.type, list.items)
    }, [group.type, list.items, onItems])
    useEffect(() => {
        onLoading(group.type, list.isLoading)
    }, [group.type, list.isLoading, onLoading])
    useEffect(() => {
        onNeedsMore(group.type, list.needsMoreSearchCharacters)
    }, [group.type, list.needsMoreSearchCharacters, onNeedsMore])
    return null
}

/** Snapshot passed to the trigger's render-prop function. */
export interface TaxonomicAutocompleteTriggerState {
    /** Whether the popover is currently open. */
    open: boolean
    /** Last entry selected through this UI; null if nothing selected (or value reset externally). */
    selected: TaxonomicAutocompleteEntry | null
    /** Display label: friendly label > raw name > placeholder > "Search…". */
    label: string
    /** Resolved placeholder, before falling back to "Search…". */
    placeholder?: string
    /** Currently controlled value from the orchestrator. */
    value: TaxonomicFilterValue | undefined
    /** Active category. */
    category: TaxonomicAutocompleteCategoryMode
    /** Drop the cached selected entry (e.g. for a "clear" button on the trigger). */
    clearSelection: () => void
}

export interface TaxonomicAutocompleteTriggerProps {
    /** Static render element passed to base-ui PopoverTrigger. */
    render?: ReactElement
    /**
     * Either a static node, or a render-function `(state) => ReactElement`
     * that receives full trigger state so the consumer can show the
     * selected value (or anything else) inside the trigger.
     */
    children?: ReactNode | ((state: TaxonomicAutocompleteTriggerState) => ReactElement)
}

function Trigger({ render, children }: TaxonomicAutocompleteTriggerProps): JSX.Element {
    const ctx = useAutocompleteCtx()
    const selected = ctx.selectedEntry
    const label =
        (selected?.friendlyLabel && selected.friendlyLabel.length > 0 ? selected.friendlyLabel : selected?.name) ||
        ctx.triggerLabel ||
        ctx.inputPlaceholder ||
        'Search…'
    const state: TaxonomicAutocompleteTriggerState = {
        open: ctx.open,
        selected,
        label,
        placeholder: ctx.inputPlaceholder,
        value: ctx.value,
        category: ctx.category,
        clearSelection: ctx.clearSelection,
    }
    let element: ReactElement
    if (typeof children === 'function') {
        element = children(state)
    } else if (render) {
        element = render
    } else {
        element = <Button variant="outline">{label}</Button>
    }
    return <PopoverTrigger render={element}>{typeof children !== 'function' ? children : null}</PopoverTrigger>
}

export interface TaxonomicAutocompleteContentProps {
    children: ReactNode
    className?: string
}

function Content({ children, className }: TaxonomicAutocompleteContentProps): JSX.Element {
    const ctx = useAutocompleteCtx()
    const inSubView = ctx.pendingEntry != null

    // Tab trap for sub-views. Scope is the popup, so Header's back button +
    // form fields all cycle. base-ui's `modal="trap-focus"` didn't loop
    // reliably with this Autocomplete.Root composition, and
    // FloatingFocusManager standalone needs a floating context we don't own.
    const handleSubViewTab = (e: React.KeyboardEvent<HTMLDivElement>): void => {
        if (!inSubView) {
            return
        }
        e.stopPropagation()
        const popupRoot = e.currentTarget
        const FOCUSABLE =
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        const tabbables = Array.from(popupRoot.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
            (el) => el.offsetParent !== null
        )
        if (tabbables.length === 0) {
            return
        }
        const first = tabbables[0]
        const last = tabbables[tabbables.length - 1]
        const active = popupRoot.ownerDocument.activeElement as HTMLElement | null
        if (e.shiftKey && active === first) {
            e.preventDefault()
            last.focus()
        } else if (!e.shiftKey && active === last) {
            e.preventDefault()
            first.focus()
        }
    }

    return (
        // Hard height pins the surface so view-stack swaps don't reflow.
        <PopoverContent
            className={cn('p-0 gap-0 w-(--anchor-width) min-w-[320px] h-[400px] overflow-hidden', className)}
        >
            <Autocomplete.Root
                items={ctx.items}
                mode="none"
                inline
                defaultOpen
                autoHighlight="always"
                openOnInputClick={false}
                itemToStringValue={(entry: IndexedItem) => entry.name}
                onItemHighlighted={(entry) => ctx.setHighlightedEntry((entry as IndexedItem | undefined) ?? null)}
            >
                {/* Wrapper owns: Esc-as-back in sub-view, Tab loop in
                    sub-view (covers Header back button + form fields), and
                    base-ui key swallowing in root view. */}
                <div
                    className="flex flex-col flex-1 min-h-0 overflow-hidden"
                    onKeyDown={(e) => {
                        if (e.key === 'Escape' && inSubView) {
                            ctx.cancelPending()
                            e.preventDefault()
                            e.stopPropagation()
                            return
                        }
                        if (e.key === 'Tab' && inSubView) {
                            handleSubViewTab(e)
                            return
                        }
                        if (
                            inSubView &&
                            (e.key === 'ArrowUp' || e.key === 'ArrowDown' || e.key === 'Home' || e.key === 'End')
                        ) {
                            e.stopPropagation()
                            return
                        }
                        stopOwnedKeys(e)
                    }}
                >
                    {children}
                </div>
            </Autocomplete.Root>
        </PopoverContent>
    )
}

export interface TaxonomicAutocompleteInputProps {
    className?: string
    placeholder?: string
}

function Input({ className, placeholder }: TaxonomicAutocompleteInputProps): JSX.Element {
    const ctx = useAutocompleteCtx()
    const categories = useTaxonomicAutocompleteCategories()
    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
        if (e.key === 'Escape') {
            // Two-step: first Escape returns from a drilled category to
            // 'all'; second Escape (already on 'all') closes the popover.
            if (ctx.category !== 'all') {
                ctx.setCategory('all')
            } else {
                ctx.setOpen(false)
            }
            e.preventDefault()
            e.stopPropagation()
            return
        }
        if (e.key === 'Enter') {
            // Autocomplete mode="none" leaves selection up to us. Prefer
            // `aria-activedescendant` (driven by `autoHighlight="always"`),
            // fall back to `[data-highlighted]` then the first option —
            // covers the brief window after returning from a sub-view
            // where the input has remounted but base-ui hasn't yet
            // reasserted activedescendant.
            const doc = e.currentTarget.ownerDocument
            const activeId = e.currentTarget.getAttribute('aria-activedescendant')
            const popupRoot = e.currentTarget.closest('[data-slot="popover-content"]')
            const itemEl =
                (activeId && (doc.getElementById(activeId) as HTMLElement | null)) ||
                (popupRoot?.querySelector('[data-highlighted]') as HTMLElement | null) ||
                (popupRoot?.querySelector('[role="option"]') as HTMLElement | null)
            if (itemEl) {
                itemEl.click()
                e.preventDefault()
                e.stopPropagation()
                return
            }
        }
        // Cycle category chips with Tab / Shift+Tab while focus stays on
        // the input. Skip when no chips are visible (sub-view active, or
        // only the synthetic 'all' entry exists) so the browser's natural
        // Tab order — i.e. tabbing into the sub-view's form — wins.
        if (e.key === 'Tab' && !ctx.pendingEntry && categories.length > 1) {
            const idx = categories.findIndex((c) => c.isActive)
            const dir = e.shiftKey ? -1 : 1
            const next = (idx + dir + categories.length) % categories.length
            categories[next]?.onSelect()
            e.preventDefault()
            e.stopPropagation()
        }
    }
    return (
        <InputGroup>
            <Autocomplete.Input
                render={
                    <InputGroupInput
                        ref={ctx.inputRef}
                        data-attr="taxonomic-filter-searchfield"
                        placeholder={placeholder ?? ctx.inputPlaceholder}
                        className={className}
                        onKeyDown={handleKeyDown}
                    />
                }
                value={ctx.searchQuery}
                onChange={(e) => ctx.setSearchQuery(e.target.value)}
            />
        </InputGroup>
    )
}

export interface TaxonomicAutocompleteListProps {
    className?: string
    children?: ReactNode
}

function List({ className, children }: TaxonomicAutocompleteListProps): JSX.Element {
    const ctx = useAutocompleteCtx()
    return (
        // Height constraint MUST live on the Viewport, not Root. Quill's
        // ScrollArea Viewport uses `height: 100%`, but `%` heights only
        // resolve when the parent has an explicit height — Root has only
        // `position: relative` plus whatever className we pass. Setting
        // `max-h-*` on Root leaves the Viewport free to size to content,
        // so `clientHeight === scrollHeight`, and base-ui never sets
        // `data-overflow-y-end` on Root, so the shadow CSS never fires.
        // Routing user className → viewportClassName makes the Viewport the
        // overflowing element, which is what base-ui measures.
        // `Autocomplete.List` itself stays non-scrollable so native
        // `scrollIntoView({block:'nearest'})` walks up to the Viewport.
        // `scroll-py-1` keeps the highlighted row from sitting flush
        // against the top/bottom edge after scroll.
        <ScrollArea
            showScrollToButton={['bottom']}
            // ScrollArea Root grows into the pinned popover envelope.
            // Padding lives on `Autocomplete.List` because Quill's main
            // `ScrollArea` (the published dist) doesn't expose
            // `viewportClassName` — passing it silently drops onto the
            // root div as an unknown DOM attribute.
            className="flex-1 min-h-0"
        >
            <Autocomplete.List data-quill className={cn('p-2 scroll-b-3 scroll-t-2', ctx.listClassName, className)}>
                {children ?? (
                    <>
                        <Empty />
                        <Items />
                    </>
                )}
            </Autocomplete.List>
        </ScrollArea>
    )
}

export interface TaxonomicAutocompleteEmptyProps {
    className?: string
    children?: ReactNode
}

function Empty({ className, children }: TaxonomicAutocompleteEmptyProps): JSX.Element {
    const ctx = useAutocompleteCtx()
    return (
        <Autocomplete.Empty className={cn('px-2 py-3 text-xs text-secondary empty:hidden', className)}>
            {children ?? ctx.emptyState}
        </Autocomplete.Empty>
    )
}

export interface TaxonomicAutocompleteItemsProps {
    /** Custom row renderer. Receives the indexed entry. */
    children?: (entry: IndexedItem) => ReactNode
}

function Items({ children }: TaxonomicAutocompleteItemsProps): JSX.Element {
    return (
        <Autocomplete.Collection>
            {(entry: IndexedItem) => (children ? children(entry) : <DefaultRow entry={entry} />)}
        </Autocomplete.Collection>
    )
}

interface DefaultRowProps {
    entry: IndexedItem
}

function DefaultRow({ entry }: DefaultRowProps): JSX.Element {
    const ctx = useAutocompleteCtx()
    const { item, group } = entry
    const rawName = entry.name
    const friendly = entry.friendlyLabel
    const title = friendly && friendly.length > 0 ? friendly : rawName
    const subtitle = friendly && friendly !== rawName ? rawName : undefined
    // Each Autocomplete.Item needs a unique id so base-ui's
    // `aria-activedescendant` only matches one row. Without a stable id,
    // base-ui falls back to a composite-list index, and identity churn in
    // the items array can cause two rows to share an id → both match
    // `data-[highlighted]` styling.
    const stableId = `taxonomic-${group.type}-${String(group.getValue?.(item) ?? rawName)}`
    // Group badge is only useful in 'all' search — it tells the user which
    // group an item came from when results from multiple groups are
    // interleaved. Inside a drilled category, every row is from the same
    // group, so the badge is just noise.
    const showGroupLabel = ctx.category === 'all'
    // Rows whose group has a `<ConfigureView>` registered (DWH, HogQL) get
    // a chevron + click-to-edit semantics.
    const hasConfigure = ctx.configuredTypes.has(group.type)
    // Hover popover by default for everything except Configure rows — the
    // chevron tells the user clicking opens an editor, a hovercard would
    // compete with that intent.
    const showHover = !hasConfigure
    const rowContent = (
        <>
            <div className="flex items-baseline gap-2 w-full">
                <span className="text-sm">
                    {title}
                    {showGroupLabel && (
                        <span className="ml-2 text-xxs uppercase tracking-wide text-secondary relative -top-px">
                            {group.name}
                        </span>
                    )}
                </span>
                {hasConfigure && <IconChevronRight className="text-secondary ml-auto" />}
            </div>
            {subtitle && <span className="text-xs text-secondary">{subtitle}</span>}
        </>
    )
    const itemClassName = cn(
        'flex flex-col items-start gap-0 rounded-sm px-2 py-1 cursor-pointer outline-none',
        'data-[highlighted]:bg-[var(--fill-selected)]'
    )

    if (!showHover) {
        return (
            <Autocomplete.Item
                value={entry}
                onClick={(e) => {
                    e.preventDefault()
                    ctx.onSelectEntry(entry)
                }}
                className={itemClassName}
                // base-ui omits `id` from `AutocompleteItem`'s prop type
                // (it assigns its own internally). Pin the stable id we
                // need via the wrap-render fallthrough.
                render={(itemProps) => <div {...itemProps} id={stableId} />}
            >
                {rowContent}
            </Autocomplete.Item>
        )
    }

    // Quill `Tooltip` is base-ui Tooltip with hoverable popup enabled by
    // default — user can move the cursor into the tooltip without it
    // closing. PreviewCard's render-composition with Autocomplete.Item
    // wasn't dispatching hover events; Tooltip's compose path is simpler.
    return (
        <Tooltip>
            <TooltipTrigger
                delay={350}
                render={(triggerProps) => (
                    <Autocomplete.Item
                        {...triggerProps}
                        value={entry}
                        onClick={(e) => {
                            e.preventDefault()
                            ctx.onSelectEntry(entry)
                        }}
                        className={itemClassName}
                        // base-ui omits `id` from `AutocompleteItem`'s
                        // prop type (it assigns its own internally). Pin
                        // the stable id via the wrap-render fallthrough.
                        render={(itemProps) => <div {...itemProps} id={stableId} />}
                    >
                        {rowContent}
                    </Autocomplete.Item>
                )}
            />
            <TooltipContent
                side="right"
                align="start"
                sideOffset={12}
                className="rounded-md border bg-popover text-popover-foreground shadow-md max-w-[320px] p-0"
            >
                <DefaultHoverBody entry={entry} />
            </TooltipContent>
        </Tooltip>
    )
}

/**
 * Default body for the row's hover popover. Reads metadata via
 * `useTaxonomicAutocompleteItemDetails`. Mirrors the layout of the
 * sub-page details sheet so the two surfaces feel consistent.
 */
function DefaultHoverBody({ entry }: { entry: TaxonomicAutocompleteEntry }): JSX.Element | null {
    const details = useTaxonomicAutocompleteItemDetails(entry)
    if (!details) {
        return null
    }
    return (
        <div className="flex flex-col gap-3 p-3 text-sm">
            <div className="flex flex-col gap-1">
                <div className="text-[10px] uppercase tracking-wide text-secondary">{details.groupLabel}</div>
                <div className="text-base font-semibold leading-tight">{details.title}</div>
            </div>
            {details.description && <p className="text-xs text-secondary">{details.description}</p>}
            {details.example && <p className="text-xs italic text-secondary">Example: {details.example}</p>}
            {details.propertyType && (
                <div className="flex flex-col gap-0.5 border-t pt-2">
                    <div className="text-[10px] uppercase tracking-wide text-secondary">Property type</div>
                    <div className="text-xs">{details.propertyType}</div>
                </div>
            )}
            {details.rawName !== details.title && (
                <div className="flex flex-col gap-0.5 border-t pt-2">
                    <div className="text-[10px] uppercase tracking-wide text-secondary">Sent as</div>
                    <code className="text-xs">{details.rawName}</code>
                </div>
            )}
        </div>
    )
}

/** Raw category list — no UI. Render however you want (chips, dropdown menu, …). */
export function useTaxonomicAutocompleteCategories(): TaxonomicAutocompleteCategory[] {
    const ctx = useAutocompleteCtx()
    return useMemo<TaxonomicAutocompleteCategory[]>(() => {
        const all: TaxonomicAutocompleteCategory = {
            id: 'all',
            name: 'All',
            isActive: ctx.category === 'all',
            onSelect: () => ctx.setCategory('all'),
        }
        const groupCats = ctx.visibleGroups.map<TaxonomicAutocompleteCategory>((group) => ({
            id: group.type,
            name: group.name,
            group,
            isActive: ctx.category === group.type,
            onSelect: () => ctx.setCategory(group.type),
            count: ctx.itemsByType[group.type]?.length,
            isLoading: ctx.loadingByType[group.type],
            needsMoreSearchCharacters: ctx.needsMoreByType[group.type],
        }))
        return [all, ...groupCats]
    }, [ctx.category, ctx.visibleGroups, ctx.setCategory, ctx.itemsByType, ctx.loadingByType, ctx.needsMoreByType, ctx])
}

/** Read raw Root state from any descendant (open/setOpen, selected, search, …). */
export function useTaxonomicAutocomplete(): {
    open: boolean
    setOpen: (v: boolean) => void
    selectedEntry: TaxonomicAutocompleteEntry | null
    clearSelection: () => void
    /** Currently keyboard/pointer-cursored row — useful for side-panel previews. */
    highlightedEntry: TaxonomicAutocompleteEntry | null
    value: TaxonomicFilterValue | undefined
    searchQuery: string
    setSearchQuery: (q: string) => void
    category: TaxonomicAutocompleteCategoryMode
    setCategory: (m: TaxonomicAutocompleteCategoryMode) => void
    items: TaxonomicAutocompleteEntry[]
    onSelectEntry: (entry: TaxonomicAutocompleteEntry) => void
    focusInput: () => void
} {
    const ctx = useAutocompleteCtx()
    return {
        open: ctx.open,
        setOpen: ctx.setOpen,
        selectedEntry: ctx.selectedEntry,
        clearSelection: ctx.clearSelection,
        highlightedEntry: ctx.highlightedEntry,
        value: ctx.value,
        searchQuery: ctx.searchQuery,
        setSearchQuery: ctx.setSearchQuery,
        category: ctx.category,
        setCategory: ctx.setCategory,
        items: ctx.items,
        onSelectEntry: ctx.onSelectEntry,
        focusInput: ctx.focusInput,
    }
}

export interface TaxonomicAutocompleteChipsProps {
    className?: string
    /** Override per-chip rendering. */
    children?: (category: TaxonomicAutocompleteCategory) => ReactNode
}

function Chips({ className, children }: TaxonomicAutocompleteChipsProps): JSX.Element {
    const categories = useTaxonomicAutocompleteCategories()
    const ctx = useAutocompleteCtx()
    return (
        <div role="tablist" className={cn('flex flex-wrap gap-1 px-2 py-1', className)}>
            {categories.map((c) =>
                children ? (
                    <span key={c.id}>{children(c)}</span>
                ) : (
                    <Button
                        key={c.id}
                        type="button"
                        role="tab"
                        size="sm"
                        aria-selected={c.isActive}
                        variant={c.isActive ? 'primary' : 'outline'}
                        // Prevent the chip from stealing focus on mousedown
                        // (so the input keeps its caret), then re-focus on
                        // click as a belt-and-braces for keyboard / touch.
                        onMouseDown={(e: React.MouseEvent<HTMLButtonElement>) => e.preventDefault()}
                        onClick={() => {
                            c.onSelect()
                            ctx.focusInput()
                        }}
                        data-attr={c.id === 'all' ? 'taxonomic-tab-all' : `taxonomic-tab-${c.id}`}
                    >
                        {c.name}
                    </Button>
                )
            )}
        </div>
    )
}

/** State passed to a `<ConfigureView>` render function. */
export interface TaxonomicAutocompleteConfigureState {
    /** The entry awaiting configuration. */
    entry: TaxonomicAutocompleteEntry
    /** Commit the entry, optionally merging extra fields into the underlying item. */
    commit: (extra?: Record<string, unknown>) => void
    /** Cancel without committing. Prior `selectedEntry` is preserved. */
    cancel: () => void
}

/**
 * Inline header rendered at the top of the popover content. Auto-shows a
 * back button (← chevron) whenever a sub-view is active, which pops the
 * view stack. Title is optional in the root view, required when a
 * `<ConfigureView>` provides one.
 */
export interface TaxonomicAutocompleteHeaderProps {
    /** Title shown when the root view is active. Sub-views render their own. */
    rootTitle?: ReactNode
    /** Title shown when a sub-view is active. Falls back to the registered view title. */
    subTitle?: ReactNode
    className?: string
}

function Header({ rootTitle, subTitle, className }: TaxonomicAutocompleteHeaderProps): JSX.Element | null {
    const ctx = useAutocompleteCtx()
    const isSub = ctx.pendingEntry != null
    const resolvedTitle = isSub ? (subTitle ?? ctx.pendingTitle ?? ctx.pendingEntry?.name) : rootTitle
    if (!resolvedTitle && !isSub) {
        return null
    }
    return (
        <div
            className={cn('flex items-center gap-2 px-3 py-2 border-b text-sm font-semibold', className)}
            data-state={isSub ? 'sub' : 'root'}
        >
            {isSub && (
                <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Back"
                    onClick={() => ctx.cancelPending()}
                    data-attr="taxonomic-autocomplete-back"
                    className="-ml-1 shrink-0"
                >
                    <IconChevronLeft className="size-4" />
                </Button>
            )}
            <span className="flex-1 truncate">{resolvedTitle}</span>
        </div>
    )
}

export interface TaxonomicAutocompleteRootViewProps {
    children: ReactNode
    className?: string
}

/**
 * Wraps the root-view content (typically `Input` + `Chips` + `List`).
 * Fully unmounts when a `<ConfigureView>` is showing — keeping it mounted
 * with `display:none` left the hidden Input's keydown handlers eligible
 * for events (notably Tab cycling chips) and made it look like the
 * sub-view couldn't take focus. Search query lives on Root, so it
 * restores naturally on remount.
 */
function RootView({ children, className }: TaxonomicAutocompleteRootViewProps): JSX.Element | null {
    const ctx = useAutocompleteCtx()
    if (ctx.pendingEntry != null) {
        return null
    }
    return (
        <div
            // `flex-1 min-h-0` so the list inside can flex-grow into the
            // pinned popover envelope (`min-h-[420px]` on PopoverContent).
            // Without `min-h-0`, flex items refuse to shrink below their
            // content height and the scroll viewport can't expand cleanly.
            className={cn('flex flex-col flex-1 min-h-0', className)}
            data-state="active"
            style={{ animation: 'taxonomic-slide-from-left 220ms cubic-bezier(0.215, 0.61, 0.355, 1)' }}
        >
            {children}
        </div>
    )
}

export interface TaxonomicAutocompleteConfigureViewProps {
    /** Group types this view handles. */
    for: readonly TaxonomicFilterGroupType[]
    /** Title for the header back-button row. */
    title?: ReactNode | ((entry: TaxonomicAutocompleteEntry) => ReactNode)
    /** Render the configuration form. Receives entry + commit/cancel callbacks. */
    children: (state: TaxonomicAutocompleteConfigureState) => ReactNode
    className?: string
}

/**
 * In-popover sub-view that activates when the user clicks a row whose
 * group is registered in `for`. Renders a header (with back button) plus
 * the consumer's form. Esc bubbles up to `Content`, which calls
 * `cancelPending` so back/Esc behave the same.
 */
function ConfigureView({
    for: forGroups,
    title,
    children,
    className,
}: TaxonomicAutocompleteConfigureViewProps): JSX.Element | null {
    const ctx = useAutocompleteCtx()
    // Register / unregister types. Stable join key avoids re-running on
    // every render even though the array literal identity changes.
    const key = forGroups.join(',')
    useEffect(() => {
        forGroups.forEach((t) => ctx.addConfiguredType(t))
        return () => forGroups.forEach((t) => ctx.removeConfiguredType(t))
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key])

    const pending = ctx.pendingPage?.kind === 'configure' ? ctx.pendingPage.entry : null
    const matches = pending != null && forGroups.includes(pending.group.type)
    const resolvedTitle = pending && title ? (typeof title === 'function' ? title(pending) : title) : pending?.name

    // Push the resolved title up to the shared Header so it can show it
    // alongside the back button. Use a layout effect to land before paint.
    useEffect(() => {
        if (matches && resolvedTitle != null) {
            ctx.setPendingTitle(resolvedTitle)
            return () => ctx.setPendingTitle(null)
        }
        return undefined
    }, [matches, resolvedTitle, ctx])

    // Move focus to the first tabbable element on mount. PopoverContent has
    // `tabIndex=-1` and Autocomplete.Root absorbs Tab — without an explicit
    // handoff, focus dies on the popover surface. Header's back button sits
    // in a sibling subtree, so this query naturally scopes to the form.
    const containerRef = useRef<HTMLDivElement | null>(null)
    useEffect(() => {
        if (!matches) {
            return
        }
        const root = containerRef.current
        if (!root) {
            return
        }
        const FOCUSABLE =
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        root.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    }, [matches])

    if (!matches || !pending) {
        return null
    }

    return (
        <div
            ref={containerRef}
            // `flex-1` so the sub-view fills the remaining popover height
            // (popover has `min-h-[420px]` to pin position). Form bodies
            // use their own `flex-1` to push the footer to the bottom.
            className={cn('flex flex-col flex-1', className)}
            data-state="active"
            style={{ animation: 'taxonomic-slide-from-right 220ms cubic-bezier(0.215, 0.61, 0.355, 1)' }}
        >
            {children({
                entry: pending,
                commit: ctx.commitPending,
                cancel: ctx.cancelPending,
            })}
        </div>
    )
}

/** State passed to a `<DetailsView>` render function. */
export interface TaxonomicAutocompleteDetailsState {
    /** The entry being viewed. */
    entry: TaxonomicAutocompleteEntry
    /** Commit the entry as the selected value (e.g. "Use this property" footer). */
    commit: (extra?: Record<string, unknown>) => void
    /** Close the details sheet, returning to the root view. */
    cancel: () => void
}

export interface TaxonomicAutocompleteDetailsViewProps {
    /** Group types this details sheet handles. */
    for: readonly TaxonomicFilterGroupType[]
    /** Title for the header back-button row. */
    title?: ReactNode | ((entry: TaxonomicAutocompleteEntry) => ReactNode)
    /** Render the details body. Receives entry + commit/cancel callbacks. */
    children: (state: TaxonomicAutocompleteDetailsState) => ReactNode
    className?: string
}

/**
 * Read-only sub-view that activates when the user navigates to the "View"
 * cell of a row (right-arrow → Enter, or click). Same chrome as
 * `<ConfigureView>` — sliding panel + Header back button — but registered
 * for the `'details'` kind. Body comes from the consumer; pair with
 * `useTaxonomicAutocompleteItemDetails(entry)` for property metadata.
 */
function DetailsView({
    for: forGroups,
    title,
    children,
    className,
}: TaxonomicAutocompleteDetailsViewProps): JSX.Element | null {
    const ctx = useAutocompleteCtx()
    const key = forGroups.join(',')
    useEffect(() => {
        forGroups.forEach((t) => ctx.addDetailsType(t))
        return () => forGroups.forEach((t) => ctx.removeDetailsType(t))
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key])

    const pending = ctx.pendingPage?.kind === 'details' ? ctx.pendingPage.entry : null
    const matches = pending != null && forGroups.includes(pending.group.type)
    const resolvedTitle = pending && title ? (typeof title === 'function' ? title(pending) : title) : pending?.name

    useEffect(() => {
        if (matches && resolvedTitle != null) {
            ctx.setPendingTitle(resolvedTitle)
            return () => ctx.setPendingTitle(null)
        }
        return undefined
    }, [matches, resolvedTitle, ctx])

    const containerRef = useRef<HTMLDivElement | null>(null)
    useEffect(() => {
        if (!matches) {
            return
        }
        const root = containerRef.current
        if (!root) {
            return
        }
        const FOCUSABLE =
            'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        root.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    }, [matches])

    if (!matches || !pending) {
        return null
    }

    return (
        <div
            ref={containerRef}
            // `flex-1` so the sub-view fills the remaining popover height
            // (popover has `min-h-[420px]` to pin position). Form bodies
            // use their own `flex-1` to push the footer to the bottom.
            className={cn('flex flex-col flex-1', className)}
            data-state="active"
            style={{ animation: 'taxonomic-slide-from-right 220ms cubic-bezier(0.215, 0.61, 0.355, 1)' }}
        >
            {children({
                entry: pending,
                commit: ctx.commitPending,
                cancel: ctx.cancelPending,
            })}
        </div>
    )
}

/**
 * Rich metadata for an autocomplete entry — title / description / type /
 * sent-as plus pin state and toggle. Pulls from kea logics
 * (`propertyDefinitionsModel` for type, `taxonomicFilterPinnedPropertiesLogic`
 * for pins) and the static `getCoreFilterDefinition` taxonomy.
 *
 * Property-typed groups (Event/Person/Session/Group properties, EventMetadata,
 * EventFeatureFlags) get a `propertyType`; others fall back to bare info.
 *
 * Returns `null` when entry is null — convenience so callers can pass the
 * possibly-null `pendingPage.entry` directly.
 */
const PROPERTY_GROUP_TYPE_TO_DEFINITION_TYPE: Partial<Record<TaxonomicFilterGroupType, PropertyDefinitionType>> = {
    [TaxonomicFilterGroupType.EventProperties]: PropertyDefinitionType.Event,
    [TaxonomicFilterGroupType.EventMetadata]: PropertyDefinitionType.Event,
    [TaxonomicFilterGroupType.EventFeatureFlags]: PropertyDefinitionType.Event,
    [TaxonomicFilterGroupType.PersonProperties]: PropertyDefinitionType.Person,
    [TaxonomicFilterGroupType.SessionProperties]: PropertyDefinitionType.Session,
    [TaxonomicFilterGroupType.GroupsPrefix]: PropertyDefinitionType.Group,
}

export interface TaxonomicAutocompleteItemDetails {
    title: string
    /** Group label, uppercased — e.g. `EVENT PROPERTY`, `PERSON PROPERTY`. */
    groupLabel: string
    /** Raw underlying name (e.g. `$browser_type`). */
    rawName: string
    description?: string
    /** First example value, formatted. */
    example?: string
    /** Property type ("String", "Numeric", …) if the group resolves to one. */
    propertyType?: string
    /** Whether the entry is currently pinned in `taxonomicFilterPinnedPropertiesLogic`. */
    isPinned: boolean
    /** Toggle pin state for the entry. */
    togglePin: () => void
    /** Whether the group supports pinning at all (META groups don't). */
    isPinnable: boolean
}

export function useTaxonomicAutocompleteItemDetails(
    entry: TaxonomicAutocompleteEntry | null
): TaxonomicAutocompleteItemDetails | null {
    const { describeProperty } = useValues(propertyDefinitionsModel)
    const { isPinned } = useValues(taxonomicFilterPinnedPropertiesLogic)
    const { togglePin: togglePinAction } = useActions(taxonomicFilterPinnedPropertiesLogic)

    return useMemo<TaxonomicAutocompleteItemDetails | null>(() => {
        if (!entry) {
            return null
        }
        const { item, group, name, friendlyLabel } = entry
        const title = friendlyLabel && friendlyLabel.length > 0 ? friendlyLabel : name
        const def = getCoreFilterDefinition(name, group.type)
        // Fall back to the pinned context's stored value when `getValue`
        // can't read it from the shrunk `{ name }` reducer payload — Actions
        // and other groups whose `getValue` reads `id` (not `name`) would
        // otherwise short-circuit to `null` and break pin/unpin from the
        // pinned drill.
        const value = group.getValue?.(item) ?? (hasPinnedContext(item) ? item._pinnedContext.value : null) ?? null
        const definitionType = PROPERTY_GROUP_TYPE_TO_DEFINITION_TYPE[group.type]
        const propertyType = definitionType ? (describeProperty(name, definitionType) ?? undefined) : undefined
        const example = def?.examples?.[0] != null ? String(def.examples[0]) : undefined
        // `group.name` is optional on synthetic groups (e.g. the
        // `ActionFilterRow` trigger-only group constructed from a
        // committed filter). Fall back to the type so the label still
        // renders something sensible instead of throwing.
        const groupLabel = (group.name ?? String(group.type ?? '')).toUpperCase()
        const isPinnable = value != null && !CURATION_META_GROUP_TYPES.has(group.type)
        // Prefer taxonomy core description (canonical events/props), fall
        // back to the item's own description (Actions, custom events, DWH
        // tables — user-authored).
        const itemDescription =
            (item as { description?: unknown })?.description &&
            typeof (item as { description?: unknown }).description === 'string'
                ? ((item as { description?: string }).description as string)
                : undefined
        // `getCoreFilterDefinition.description` is typed as `ReactNode`
        // (some core defs ship JSX); narrow to string here so the
        // returned `TaxonomicAutocompleteItemDetails.description?: string`
        // contract holds. Lossy for JSX-shaped descriptions, but the
        // current consumers all render plain strings anyway.
        const coreDescription = typeof def?.description === 'string' ? def.description : undefined
        return {
            title,
            groupLabel,
            rawName: name,
            description: coreDescription ?? itemDescription,
            example,
            propertyType: propertyType ? String(propertyType) : undefined,
            isPinned: isPinnable ? isPinned(group.type, value) : false,
            isPinnable,
            togglePin: () => {
                if (isPinnable) {
                    togglePinAction(group.type, group.name, value, item)
                }
            },
        }
    }, [entry, describeProperty, isPinned, togglePinAction])
}

// View-stack slide animations injected once at module load. ease-out-cubic
// (Quill's popover-content easing) at 220ms — long enough to read the
// motion as a "slide" without delaying interaction. 16px travel matches
// what feels like a half-step rather than a twitch. Pseudo-elements don't
// need them; only the two keyframes are exposed.
const VIEW_ANIMATIONS_STYLE_ID = 'taxonomic-autocomplete-view-animations'
if (typeof document !== 'undefined' && !document.getElementById(VIEW_ANIMATIONS_STYLE_ID)) {
    const styleEl = document.createElement('style')
    styleEl.id = VIEW_ANIMATIONS_STYLE_ID
    styleEl.textContent = `
@keyframes taxonomic-slide-from-right {
    from { transform: translateX(16px); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}
@keyframes taxonomic-slide-from-left {
    from { transform: translateX(-16px); opacity: 0; }
    to { transform: translateX(0); opacity: 1; }
}
@media (prefers-reduced-motion: reduce) {
    [data-state="active"] {
        animation: none !important;
    }
}
`
    document.head.appendChild(styleEl)
}

export interface TaxonomicAutocompleteSegmentedTriggerProps {
    /** Render the group segment. Defaults to `selected.group.name`. */
    renderGroup?: (entry: TaxonomicAutocompleteEntry) => ReactNode
    /** Render the item segment. Defaults to friendly label or raw name. */
    renderItem?: (entry: TaxonomicAutocompleteEntry) => ReactNode
    /** Hide the trailing × button. */
    hideClear?: boolean
    /**
     * Render when nothing is selected. Defaults to a single Button using
     * `triggerLabel` / placeholder fallback.
     */
    renderEmpty?: () => ReactElement
    className?: string
}

/**
 * `[group | item | ×]` button group. Group segment opens the picker
 * (drilled to the selected category); item segment re-opens the
 * configurator for the entry (or the picker, if no configurator
 * registered); × clears.
 */
function SegmentedTrigger({
    renderGroup,
    renderItem,
    hideClear = false,
    renderEmpty,
    className,
}: TaxonomicAutocompleteSegmentedTriggerProps): JSX.Element {
    const ctx = useAutocompleteCtx()
    const selected = ctx.selectedEntry

    if (!selected) {
        const fallback = renderEmpty ? (
            renderEmpty()
        ) : (
            <Button variant="outline">{ctx.triggerLabel ?? ctx.inputPlaceholder ?? 'Select…'}</Button>
        )
        return <PopoverTrigger render={fallback} />
    }

    const itemHasConfigurator = ctx.configuredTypes.has(selected.group.type)
    const itemContent = renderItem ? renderItem(selected) : selected.friendlyLabel || selected.name
    const groupContent = renderGroup ? renderGroup(selected) : selected.group.name

    return (
        <ButtonGroup className={className}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        onClick={() => ctx.setCategory(selected.group.type)}
                        data-attr="taxonomic-autocomplete-segment-group"
                    >
                        {groupContent}
                    </Button>
                }
            />
            <Button
                variant="outline"
                data-attr="taxonomic-autocomplete-segment-item"
                onClick={() => {
                    if (itemHasConfigurator) {
                        ctx.openConfigureFor(selected)
                    } else {
                        ctx.setOpen(true)
                    }
                }}
            >
                {itemContent}
            </Button>
            {!hideClear && (
                <Button
                    variant="outline"
                    aria-label="Clear selection"
                    data-attr="taxonomic-autocomplete-segment-clear"
                    onClick={(e: React.MouseEvent<HTMLButtonElement>) => {
                        e.stopPropagation()
                        ctx.clearSelection()
                    }}
                >
                    ×
                </Button>
            )}
        </ButtonGroup>
    )
}

/**
 * Pinned + suggested entries surfaced through `<MenuTrigger>` shortcuts.
 * Pinned items come from `taxonomicFilterPinnedPropertiesLogic`; suggested
 * items come from the orchestrator's synthetic `SuggestedFilters` group
 * (`group.options`). Both are mapped back to the source group so
 * `ctx.onSelectEntry(entry)` commits to the right group.
 */
export function useTaxonomicAutocompleteShortcutItems(): {
    pinned: TaxonomicAutocompleteEntry[]
    suggested: TaxonomicAutocompleteEntry[]
} {
    const { groups } = useTaxonomicFilterContext()
    const { pinnedFilterItems } = useValues(taxonomicFilterPinnedPropertiesLogic)

    return useMemo<{ pinned: TaxonomicAutocompleteEntry[]; suggested: TaxonomicAutocompleteEntry[] }>(() => {
        const findGroup = (type: TaxonomicFilterGroupType | undefined): TaxonomicFilterGroup | undefined =>
            type ? groups.find((g) => g.type === type) : undefined

        const buildEntry = (
            item: TaxonomicDefinitionTypes,
            sourceType: TaxonomicFilterGroupType | undefined
        ): TaxonomicAutocompleteEntry | null => {
            const group = findGroup(sourceType)
            if (!group) {
                return null
            }
            const name = getRawName(item, group)
            return { item, group, name, friendlyLabel: getFriendlyLabel(item, group) }
        }

        const pinned: TaxonomicAutocompleteEntry[] = (
            pinnedFilterItems as Array<
                TaxonomicDefinitionTypes & { _pinnedContext?: { sourceGroupType?: TaxonomicFilterGroupType } }
            >
        )
            .map((item) => buildEntry(item, item._pinnedContext?.sourceGroupType))
            .filter((e): e is TaxonomicAutocompleteEntry => e != null)

        const suggestedGroup = findGroup(TaxonomicFilterGroupType.SuggestedFilters)
        const suggestedOptions = ((
            suggestedGroup as { options?: Array<{ name: string; group: TaxonomicFilterGroupType }> } | undefined
        )?.options ?? []) as Array<{ name: string; group: TaxonomicFilterGroupType }>
        const suggested: TaxonomicAutocompleteEntry[] = suggestedOptions
            .map((opt) => buildEntry({ name: opt.name } as unknown as TaxonomicDefinitionTypes, opt.group))
            .filter((e): e is TaxonomicAutocompleteEntry => e != null)

        return { pinned, suggested }
    }, [groups, pinnedFilterItems])
}

const DEFAULT_MENU_SHORTCUT_GROUPS: readonly TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.DataWarehouse,
    TaxonomicFilterGroupType.HogQLExpression,
]

export interface TaxonomicAutocompleteMenuTriggerProps {
    /**
     * Group types managed by the menu — surfaced as menu items, removed
     * from popover chips/list. Default: DataWarehouse + HogQLExpression.
     */
    shortcutGroups?: readonly TaxonomicFilterGroupType[]
    /** Label for the "open the search popover" menu item. */
    chooseFilterLabel?: ReactNode
    /** Static render element passed to the menu trigger. */
    render?: ReactElement
    /** Render-function form. Receives full trigger state. */
    children?: ReactNode | ((state: TaxonomicAutocompleteTriggerState) => ReactElement)
}

/**
 * Dropdown-menu trigger that fronts the popover with quick-action items.
 * Click → opens menu, menu offers:
 *   - "Choose filter…" → opens the popover (search list)
 *   - Pinned items → commit directly
 *   - Suggested items → commit directly
 *   - Per-shortcut group → DWH opens popover at DWH category, HogQL opens
 *     the editor sub-page
 *
 * Composes Popover + DropdownMenu on the same button via `render` so the
 * popover can still anchor to the trigger (PopoverWrapper gates the
 * trigger-press so the click only opens the menu, not the popover).
 */
function MenuTrigger({
    shortcutGroups = DEFAULT_MENU_SHORTCUT_GROUPS,
    chooseFilterLabel = 'Choose filter…',
    render,
    children,
}: TaxonomicAutocompleteMenuTriggerProps): JSX.Element {
    const ctx = useAutocompleteCtx()
    const { groups } = useTaxonomicFilterContext()
    const { pinned, suggested } = useTaxonomicAutocompleteShortcutItems()
    const [menuOpen, setMenuOpen] = useState(false)

    // Register shortcut groups + flag the trigger so PopoverWrapper gates
    // the trigger-press. Stable join key avoids re-running on render.
    const key = shortcutGroups.join(',')
    useEffect(() => {
        shortcutGroups.forEach((t) => ctx.addDropdownManagedType(t))
        ctx.setHasMenuTrigger(true)
        return () => {
            shortcutGroups.forEach((t) => ctx.removeDropdownManagedType(t))
            ctx.setHasMenuTrigger(false)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [key])

    const selected = ctx.selectedEntry
    const label =
        (selected?.friendlyLabel && selected.friendlyLabel.length > 0 ? selected.friendlyLabel : selected?.name) ||
        ctx.triggerLabel ||
        ctx.inputPlaceholder ||
        'Filter'
    const state: TaxonomicAutocompleteTriggerState = {
        open: ctx.open,
        selected,
        label,
        placeholder: ctx.inputPlaceholder,
        value: ctx.value,
        category: ctx.category,
        clearSelection: ctx.clearSelection,
    }
    let triggerEl: ReactElement
    if (typeof children === 'function') {
        triggerEl = children(state)
    } else if (render) {
        triggerEl = render
    } else {
        triggerEl = <Button variant="outline">{label}</Button>
    }

    const dwhGroup = groups.find((g) => g.type === TaxonomicFilterGroupType.DataWarehouse)
    const hogqlGroup = groups.find((g) => g.type === TaxonomicFilterGroupType.HogQLExpression)
    const showDwhShortcut = shortcutGroups.includes(TaxonomicFilterGroupType.DataWarehouse) && !!dwhGroup
    const showHogqlShortcut = shortcutGroups.includes(TaxonomicFilterGroupType.HogQLExpression) && !!hogqlGroup

    return (
        <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen}>
            {/* Single button = both the menu trigger AND the popover anchor.
                base-ui composes both components' props onto the same DOM
                node via render. Clicks open the menu; the popover's
                trigger-press reason is dropped in PopoverWrapper so it
                doesn't auto-open. Programmatic opens (menu items calling
                ctx.setOpen) bypass the gate. */}
            <DropdownMenuTrigger render={<PopoverTrigger render={triggerEl} />} />
            <DropdownMenuContent align="start" className="min-w-[240px]">
                <DropdownMenuItem
                    onClick={() => {
                        setMenuOpen(false)
                        ctx.setOpen(true)
                    }}
                    data-attr="taxonomic-menu-choose-filter"
                >
                    {chooseFilterLabel}
                </DropdownMenuItem>
                {pinned.length > 0 && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Pinned</DropdownMenuLabel>
                            {pinned.map((entry) => {
                                const entryValue = entry.group.getValue?.(entry.item)
                                const itemKey = `pinned-${entry.group.type}-${String(entryValue ?? entry.name)}`
                                return (
                                    <DropdownMenuItem
                                        key={itemKey}
                                        onClick={() => {
                                            setMenuOpen(false)
                                            ctx.onSelectEntry(entry)
                                        }}
                                    >
                                        {entry.friendlyLabel ?? entry.name}
                                    </DropdownMenuItem>
                                )
                            })}
                        </DropdownMenuGroup>
                    </>
                )}
                {suggested.length > 0 && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Suggested</DropdownMenuLabel>
                            {suggested.map((entry) => {
                                const entryValue = entry.group.getValue?.(entry.item)
                                const itemKey = `suggested-${entry.group.type}-${String(entryValue ?? entry.name)}`
                                return (
                                    <DropdownMenuItem
                                        key={itemKey}
                                        onClick={() => {
                                            setMenuOpen(false)
                                            ctx.onSelectEntry(entry)
                                        }}
                                    >
                                        {entry.friendlyLabel ?? entry.name}
                                    </DropdownMenuItem>
                                )
                            })}
                        </DropdownMenuGroup>
                    </>
                )}
                {(showDwhShortcut || showHogqlShortcut) && <DropdownMenuSeparator />}
                {showDwhShortcut && dwhGroup && (
                    <DropdownMenuItem
                        onClick={() => {
                            setMenuOpen(false)
                            ctx.setCategory(TaxonomicFilterGroupType.DataWarehouse)
                            ctx.setOpen(true)
                        }}
                        data-attr="taxonomic-menu-shortcut-dwh"
                    >
                        {dwhGroup.name}
                    </DropdownMenuItem>
                )}
                {showHogqlShortcut && hogqlGroup && (
                    <DropdownMenuItem
                        onClick={() => {
                            setMenuOpen(false)
                            const synthetic: IndexedItem = {
                                item: { name: hogqlGroup.name } as TaxonomicDefinitionTypes,
                                group: hogqlGroup,
                                name: hogqlGroup.name,
                            }
                            ctx.openConfigureFor(synthetic)
                            ctx.setOpen(true)
                        }}
                        data-attr="taxonomic-menu-shortcut-hogql"
                    >
                        {hogqlGroup.name}
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

export const TaxonomicAutocomplete = {
    Root,
    Popover: PopoverWrapper,
    Trigger,
    MenuTrigger,
    SegmentedTrigger,
    Content,
    Header,
    RootView,
    ConfigureView,
    DetailsView,
    Input,
    Chips,
    List,
    Empty,
    Items,
}

/**
 * Convenience composition that mirrors the previous monolithic component.
 * Renders trigger + popover with input on top, category chips below input,
 * then the result list. Use the granular `TaxonomicAutocomplete.*` parts
 * (and `useTaxonomicAutocompleteCategories`) when you need a different
 * layout — e.g. categories as a dropdown menu instead of chips.
 */
export interface TaxonomicFilterAutocompleteInputProps extends Omit<TaxonomicAutocompleteRootProps, 'children'> {
    /**
     * Custom trigger. Either a static element, or a render function
     * `(state) => ReactElement` that receives full trigger state (selected
     * entry, value, open, label, …) so the consumer can render the trigger
     * however they want — e.g. show the selected value as a chip.
     */
    trigger?: ReactElement | ((state: TaxonomicAutocompleteTriggerState) => ReactElement)
    /** Class on the popover content surface. */
    contentClassName?: string
}

export function TaxonomicFilterAutocompleteInput({
    trigger,
    contentClassName,
    ...rootProps
}: TaxonomicFilterAutocompleteInputProps): JSX.Element | null {
    return (
        <TaxonomicAutocomplete.Root {...rootProps}>
            <TaxonomicAutocomplete.Popover>
                {typeof trigger === 'function' ? (
                    <TaxonomicAutocomplete.Trigger>{trigger}</TaxonomicAutocomplete.Trigger>
                ) : (
                    <TaxonomicAutocomplete.Trigger render={trigger} />
                )}
                <TaxonomicAutocomplete.Content className={contentClassName}>
                    <TaxonomicAutocomplete.Header />
                    <TaxonomicAutocomplete.RootView>
                        <div className="p-4">
                            <TaxonomicAutocomplete.Input />
                        </div>
                        <TaxonomicAutocomplete.Chips className="border-t" />
                        <TaxonomicAutocomplete.List />
                    </TaxonomicAutocomplete.RootView>
                </TaxonomicAutocomplete.Content>
            </TaxonomicAutocomplete.Popover>
        </TaxonomicAutocomplete.Root>
    )
}
