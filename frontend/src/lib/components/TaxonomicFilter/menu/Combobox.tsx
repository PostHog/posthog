/**
 * Combobox panel — search input + (optional) category chips + result list.
 *
 * Drives the popover when the user picks "New filter…", "Recent",
 * "Pinned", or any specific group. When `drillTo` is set, chips are
 * hidden and the list is locked to that drill scope. Search filters
 * within the active scope only.
 *
 * Built on `@base-ui/react/autocomplete` for keyboard navigation +
 * `aria-activedescendant` plumbing. Single-cell rows. Click or Enter to
 * commit. Esc → onBack.
 */
import { Autocomplete } from '@base-ui/react/autocomplete'
import FuseClass from 'fuse.js'
import { Check, ChevronRight } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Button, cn, InputGroup, InputGroupInput, MenuLabel, ScrollArea, Separator } from '@posthog/quill'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { useTaxonomicFilterContext } from '../headless/context'
import { useGroupList } from '../hooks/useGroupList'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../types'
import { MenuFilterHeader } from './Header'
import { PreviewPane } from './PreviewPane'
import { CommitFn, DrillCategory, MenuFilterEntry } from './types'

const FUSE_OPTIONS = {
    keys: ['name', 'friendlyLabel'],
    threshold: 0.3,
    ignoreDiacritics: true,
    ignoreLocation: true,
}

/** Categories filtered out of the chip row when drillTo === 'all'. */
const HIDDEN_FROM_CHIPS: ReadonlySet<TaxonomicFilterGroupType> = new Set([
    // `SuggestedFilters` from taxonomicFilterLogic is a tiny set of
    // primary-property promotions for the *currently-selected event* +
    // autocapture text/selector. It's empty for almost every flow that
    // doesn't have an event-in-context, and even when populated it
    // duplicates what shows up under Event properties. Hide entirely;
    // our own `Suggested` chip (Recent ∪ Pinned) covers what users
    // actually want.
    TaxonomicFilterGroupType.SuggestedFilters,
    // RecentFilters / PinnedFilters surface via the dropdown menu
    // (Recent / Pinned entries with chevrons), DataWarehouse + HogQL
    // expression have their own dedicated panels — none of them belong
    // in the in-combobox chip row.
    TaxonomicFilterGroupType.RecentFilters,
    TaxonomicFilterGroupType.PinnedFilters,
    TaxonomicFilterGroupType.DataWarehouse,
    TaxonomicFilterGroupType.HogQLExpression,
])

export interface MenuFilterComboboxProps {
    drillTo: DrillCategory
    /** Pre-resolved entries for `drillTo='recent' | 'pinned'`. Skips fetching. */
    drillItems?: MenuFilterEntry[]
    /** Pre-resolved entries for the `'suggested'` chip / drill — Recent ∪ Pinned across groups. Always passed; used whenever the active scope is `'suggested'` regardless of `drillTo`. */
    suggestedItems?: MenuFilterEntry[]
    placeholder?: string
    onCommit: CommitFn
    onBack: () => void
    /** Title shown in the header. Defaults to drill category name. */
    title?: string
    /** Currently-committed selection — rendered with a checkmark + scrolled into view. */
    selectedEntry?: MenuFilterEntry | null
}

export function MenuFilterCombobox({
    drillTo,
    drillItems,
    suggestedItems,
    placeholder,
    onCommit,
    onBack,
    title,
    selectedEntry,
}: MenuFilterComboboxProps): JSX.Element {
    // Sync our local query to the orchestrator's so remote-endpoint groups
    // (Pageview URLs, Screens, etc.) actually fetch — `useGroupList` reads
    // `searchQuery` from the orchestrator's `getGroupListInput`, not from
    // us. Keeping a local mirror just for the controlled input ergonomics.
    const { groups, searchQuery, setSearchQuery } = useTaxonomicFilterContext()
    // When opening with chips visible (`drillTo='all'`) and a current
    // selection exists, start on the matching chip so the user lands on
    // their selection's category by default — they can still tab back to
    // "All" or any other chip without leaving the combobox.
    const [activeChip, setActiveChip] = useState<DrillCategory>(() => {
        if (drillTo === 'all' && selectedEntry) {
            return selectedEntry.group.type
        }
        return drillTo
    })
    const [itemsByType, setItemsByType] = useState<Record<string, TaxonomicDefinitionTypes[]>>({})
    // Seed the highlight with the committed selection so the preview
    // pane shows the right definition before any row hovers fire. Once
    // the list mounts, `autoHighlight="always"` + the reordered
    // `filtered` (selected entry promoted to index 0) keeps the
    // highlight on the same row.
    const [highlightedEntry, setHighlightedEntry] = useState<MenuFilterEntry | null>(selectedEntry ?? null)
    const inputRef = useRef<HTMLInputElement | null>(null)

    // Stable DOM id for the selected row — must mirror `Row`'s `stableId`
    // so the checkmark + scroll target can be derived identically here.
    const selectedRowId = useMemo<string | null>(() => {
        if (!selectedEntry) {
            return null
        }
        const value = selectedEntry.group.getValue?.(selectedEntry.item) ?? selectedEntry.name
        return `menu-filter-row-${selectedEntry.group.type}-${String(value)}`
    }, [selectedEntry])

    // Scroll the selected row into view after the list mounts. Polls a few
    // animation frames because rows render after the underlying group's
    // items resolve (remote endpoints), so the element won't exist on the
    // first paint. Stops as soon as the node appears or after ~10 frames.
    useEffect(() => {
        if (!selectedRowId) {
            return
        }
        let cancelled = false
        let attempts = 0
        const tick = (): void => {
            if (cancelled) {
                return
            }
            const el = document.getElementById(selectedRowId)
            if (el) {
                // `center` keeps a comfortable buffer above + below the
                // selected row so it never lands flush against the edge
                // of the scroll viewport (where the scroll-to button or
                // the scrollbar fade can obscure it).
                el.scrollIntoView({ block: 'center' })
                return
            }
            if (attempts++ < 10) {
                requestAnimationFrame(tick)
            }
        }
        tick()
        return () => {
            cancelled = true
        }
    }, [selectedRowId])

    const reportItems = useCallback((type: string, next: TaxonomicDefinitionTypes[]): void => {
        setItemsByType((prev) => (prev[type] === next ? prev : { ...prev, [type]: next }))
    }, [])

    // Chips show only when `drillTo='all'` — drilled scopes lock to one
    // category and hide the chip row per spec.
    const showChips = drillTo === 'all'
    const visibleChipGroups = useMemo(() => groups.filter((g) => !HIDDEN_FROM_CHIPS.has(g.type)), [groups])

    // Resolve which groups feed the visible list, based on the active chip
    // (or the drill scope when chips are hidden).
    const targetGroups = useMemo<TaxonomicFilterGroup[]>(() => {
        const scope = showChips ? activeChip : drillTo
        if (scope === 'all') {
            return visibleChipGroups
        }
        if (scope === 'recent' || scope === 'pinned' || scope === 'suggested') {
            return [] // items come from `drillItems` / `suggestedItems`
        }
        const g = groups.find((gr) => gr.type === scope)
        return g ? [g] : []
    }, [showChips, activeChip, drillTo, groups, visibleChipGroups])

    // Indexed entries — flat list across all visible groups (or
    // pre-resolved `drillItems` for recent/pinned, or pre-merged
    // `suggestedItems` for the Suggested chip / drill).
    const indexed = useMemo<MenuFilterEntry[]>(() => {
        const scope = showChips ? activeChip : drillTo
        if (scope === 'suggested' && suggestedItems) {
            return suggestedItems
        }
        if (drillItems) {
            return drillItems
        }
        const merged: MenuFilterEntry[] = []
        for (const group of targetGroups) {
            const items = itemsByType[group.type] ?? []
            for (const item of items) {
                merged.push({
                    item,
                    group,
                    name: getRawName(item, group),
                    friendlyLabel: getFriendlyLabel(item, group),
                })
            }
        }
        // Make sure the committed selection is reachable from the list
        // even when the remote endpoint paginated past it (limit=100,
        // alphabetical ordering — long-tail custom events get cut off
        // and the user can't see what they previously picked). Prepend
        // it if missing so it's clickable, scroll-able, and feeds the
        // preview pane. Skip when the active chip filters it out
        // (showing it under the wrong category would lie to the user).
        if (selectedEntry) {
            const fitsScope =
                scope === 'all' ||
                scope === selectedEntry.group.type ||
                scope === 'recent' ||
                scope === 'pinned' ||
                scope === 'suggested'
            if (fitsScope) {
                const selectedValue = selectedEntry.group.getValue?.(selectedEntry.item) ?? selectedEntry.name
                const present = merged.some(
                    (e) =>
                        e.group.type === selectedEntry.group.type &&
                        (e.group.getValue?.(e.item) ?? e.name) === selectedValue
                )
                if (!present) {
                    merged.unshift(selectedEntry)
                }
            }
        }
        return merged
    }, [drillItems, suggestedItems, targetGroups, itemsByType, selectedEntry, showChips, activeChip, drillTo])

    const filtered = useMemo<MenuFilterEntry[]>(() => {
        const q = searchQuery.trim()
        const base = q ? new FuseClass(indexed, FUSE_OPTIONS as any).search(q).map((r) => r.item) : indexed
        // Promote the committed selection to index 0 so base-ui's
        // `autoHighlight="always"` lands on it the moment the list
        // mounts — keyboard nav starts on the selected row, the
        // preview pane shows the right definition, and `Enter` re-commits
        // without forcing the user to scroll. Skip when the user has
        // typed a search query — relevance order should win there.
        if (!q && selectedRowId) {
            const idx = base.findIndex(
                (e) =>
                    `menu-filter-row-${e.group.type}-${String(e.group.getValue?.(e.item) ?? e.name)}` === selectedRowId
            )
            if (idx > 0) {
                return [base[idx], ...base.slice(0, idx), ...base.slice(idx + 1)]
            }
        }
        return base
    }, [indexed, searchQuery, selectedRowId])

    // Active-chip-aware placeholder. When the user has narrowed to a
    // specific category, use that group's `searchPlaceholder` so the
    // input reflects the search scope ("Search events" vs. the broad
    // "Search events, actions, …").
    const activePlaceholder = useMemo(() => {
        if (activeChip === 'all') {
            return placeholder ?? 'Search…'
        }
        if (activeChip === 'recent' || activeChip === 'pinned' || activeChip === 'suggested') {
            return placeholder ?? 'Search…'
        }
        const group = groups.find((g) => g.type === activeChip)
        const phrase = group?.searchPlaceholder ?? group?.name?.toLowerCase()
        return phrase ? `Search ${phrase}…` : (placeholder ?? 'Search…')
    }, [activeChip, groups, placeholder])

    // Empty-state message. Three branches:
    //   - "needs more characters" — when the active chip resolves to a
    //     single group with `minSearchQueryLength` and the search query
    //     is shorter than that. Shows the group's `searchDescription`
    //     to explain what the typing will reach (matching the
    //     screenshot in the design).
    //   - "no matches" — search query is long enough but nothing
    //     resolved. Names the active category for context.
    //   - "no items" — initial render with no search and no resolved
    //     entries (rare for finite groups).
    const emptyState = useMemo<{ title: string; body?: string } | null>(() => {
        if (filtered.length > 0) {
            return null
        }
        const scope = showChips ? activeChip : drillTo
        const singleGroup =
            scope !== 'all' && scope !== 'recent' && scope !== 'pinned'
                ? (groups.find((g) => g.type === scope) ?? null)
                : null
        const minLen = singleGroup?.minSearchQueryLength ?? 0
        const trimmedLen = searchQuery.trim().length
        if (singleGroup && minLen > 0 && trimmedLen < minLen) {
            const description = singleGroup.searchDescription ?? singleGroup.name.toLowerCase()
            return {
                title: singleGroup.name,
                body: `Type at least ${minLen} characters to search ${description} we have seen.`,
            }
        }
        const categoryLabel = singleGroup?.name ?? (showChips ? null : null)
        if (trimmedLen > 0) {
            return {
                title: categoryLabel ? `No "${categoryLabel}" found` : 'No matches',
            }
        }
        return {
            title: categoryLabel ? `No "${categoryLabel}" found` : 'No items',
        }
    }, [filtered.length, showChips, activeChip, drillTo, groups, searchQuery])

    const headerTitle =
        title ??
        (drillTo === 'all'
            ? 'Choose filter'
            : drillTo === 'recent'
              ? 'Recent'
              : drillTo === 'pinned'
                ? 'Pinned'
                : drillTo === 'suggested'
                  ? 'Suggested'
                  : (groups.find((g) => g.type === drillTo)?.name ?? 'Filter'))

    const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>): void => {
        if (e.key === 'Escape') {
            onBack()
            e.preventDefault()
            e.stopPropagation()
            return
        }
        if (e.key === 'Enter') {
            // mode="none" → no auto-selection. Click the highlighted row
            // (tracked by base-ui via `aria-activedescendant`) to commit.
            const activeId = e.currentTarget.getAttribute('aria-activedescendant')
            if (activeId) {
                const el = e.currentTarget.ownerDocument.getElementById(activeId) as HTMLElement | null
                el?.click()
                e.preventDefault()
                e.stopPropagation()
            }
            return
        }
        if (e.key === 'Tab' && showChips && visibleChipGroups.length > 0) {
            // Cycle chips while focus stays on input. Wraps both directions.
            const ordered: DrillCategory[] = [
                'all',
                ...(suggestedItems && suggestedItems.length > 0 ? (['suggested'] as const) : []),
                ...visibleChipGroups.map((g) => g.type),
            ]
            const idx = ordered.indexOf(activeChip)
            const dir = e.shiftKey ? -1 : 1
            const next = ordered[(idx + dir + ordered.length) % ordered.length]
            setActiveChip(next)
            e.preventDefault()
            e.stopPropagation()
        }
    }

    return (
        <div className="flex flex-col flex-1 min-h-0">
            <MenuFilterHeader
                title={headerTitle}
                onBack={onBack}
                // Tab cycles the chip row — hide the hint when chips
                // aren't visible (drilled views, Recent / Pinned), since
                // there's nothing to cycle through.
                showTabHint={showChips && visibleChipGroups.length > 0}
            />
            <Autocomplete.Root
                items={filtered}
                mode="none"
                inline
                defaultOpen
                autoHighlight="always"
                // `keepHighlight` so moving the pointer off the list (into
                // the preview pane to click Pin / Edit / View) doesn't
                // reset to the first row and pull the preview out from
                // under the user.
                keepHighlight
                openOnInputClick={false}
                itemToStringValue={(entry: MenuFilterEntry) => entry.name}
                onItemHighlighted={(entry) => setHighlightedEntry((entry as MenuFilterEntry | undefined) ?? null)}
            >
                {/* Flex layout: list flexes, separator is 1px, preview is a
                    fixed 300px column. `shrink-0` on the preview keeps it
                    stable when the popover (or list contents) change width. */}
                <div className="flex flex-1 min-h-0">
                    <div className="flex flex-col flex-1 min-w-0 min-h-0">
                        <div className="p-2 border-b">
                            <InputGroup>
                                <Autocomplete.Input
                                    render={
                                        <InputGroupInput
                                            ref={inputRef}
                                            autoFocus
                                            data-attr="menu-filter-search"
                                            placeholder={activePlaceholder}
                                            onKeyDown={handleInputKeyDown}
                                        />
                                    }
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                />
                            </InputGroup>
                        </div>
                        {showChips && (
                            <div role="tablist" className="flex flex-wrap gap-1 px-2 py-1 border-b">
                                <ChipButton
                                    label="All"
                                    active={activeChip === 'all'}
                                    onSelect={() => {
                                        setActiveChip('all')
                                        inputRef.current?.focus()
                                    }}
                                />
                                {/* `Suggested` chip = Recent ∪ Pinned across
                                    groups. Only render when there's something
                                    to surface — empty Suggested just adds
                                    visual noise. */}
                                {suggestedItems && suggestedItems.length > 0 && (
                                    <ChipButton
                                        label="Suggested"
                                        active={activeChip === 'suggested'}
                                        onSelect={() => {
                                            setActiveChip('suggested')
                                            inputRef.current?.focus()
                                        }}
                                    />
                                )}
                                {visibleChipGroups.map((g) => (
                                    <ChipButton
                                        key={g.type}
                                        label={g.name}
                                        active={activeChip === g.type}
                                        onSelect={() => {
                                            setActiveChip(g.type)
                                            inputRef.current?.focus()
                                        }}
                                    />
                                ))}
                            </div>
                        )}
                        {!drillItems &&
                            targetGroups.map((g) => <Fetcher key={g.type} group={g} onItems={reportItems} />)}
                        <ScrollArea className="flex-1 min-h-0 scroll-py-8" alwaysShowScrollbars>
                            <Autocomplete.List data-quill className="p-2 scroll-py-8">
                                <Autocomplete.Empty className="empty:hidden">
                                    {emptyState && (
                                        <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
                                            <div className="text-sm font-semibold">{emptyState.title}</div>
                                            {emptyState.body && (
                                                <div className="text-xs text-secondary leading-relaxed">
                                                    {emptyState.body}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </Autocomplete.Empty>
                                <Autocomplete.Collection>
                                    {(entry: MenuFilterEntry) => (
                                        <Row
                                            entry={entry}
                                            // Show the category label on mixed-group views (All)
                                            // and on Recent/Pinned drills — those mix items from
                                            // multiple categories so the label disambiguates.
                                            // Drilled-to-one-group views skip it (the panel
                                            // header / chip already names the category).
                                            showCategory={
                                                activeChip === 'all' || drillTo === 'recent' || drillTo === 'pinned'
                                            }
                                            // DWH rows open the column-config
                                            // form, not a final selection —
                                            // signal that with a chevron.
                                            opensSubmenu={drillTo === TaxonomicFilterGroupType.DataWarehouse}
                                            selectedRowId={selectedRowId}
                                            onCommit={onCommit}
                                        />
                                    )}
                                </Autocomplete.Collection>
                            </Autocomplete.List>
                        </ScrollArea>
                    </div>
                    <Separator orientation="vertical" className="h-full hidden md:block" />
                    <PreviewPane
                        entry={highlightedEntry}
                        className="hidden md:flex flex-col w-[300px] shrink-0 min-w-0"
                    />
                </div>
            </Autocomplete.Root>
        </div>
    )
}

interface RowProps {
    entry: MenuFilterEntry
    /** Render the category label (mixed-group views always; drilled views skip it since the panel header already names the group). */
    showCategory: boolean
    /** Show a trailing chevron when click drills to another panel (DWH config). */
    opensSubmenu?: boolean
    /** DOM id of the currently-selected row (for the trailing checkmark). */
    selectedRowId?: string | null
    onCommit: CommitFn
}

/**
 * Resolve a row's three normalized cells:
 *   - name:     human-friendly label (e.g. "Pageview", "/checkout")
 *   - value:    raw underlying value when distinct from the name
 *               (e.g. "$pageview", "localhost:8010")
 *   - category: group name shown as an uppercase tag at the bottom
 *
 * URLs split into path (name) + host (value); friendly definitions
 * surface the friendly label as the name and the raw `$key` as the
 * value; everything else uses the entry name as the name and omits
 * the value cell.
 */
function resolveRowCells(entry: MenuFilterEntry): { name: string; value?: string; category: string } {
    const friendly = entry.friendlyLabel
    const url = parseUrl(entry.name)
    if (url) {
        return { name: url.pathTail, value: url.host, category: entry.group.name }
    }
    if (friendly && friendly.length > 0 && friendly !== entry.name) {
        return { name: friendly, value: entry.name, category: entry.group.name }
    }
    return { name: entry.name, category: entry.group.name }
}

function Row({ entry, showCategory, opensSubmenu, selectedRowId, onCommit }: RowProps): JSX.Element {
    const { item, group } = entry
    const { name, value, category } = resolveRowCells(entry)
    const stableId = `menu-filter-row-${group.type}-${String(group.getValue?.(item) ?? entry.name)}`
    const isSelected = selectedRowId === stableId
    return (
        <Autocomplete.Item
            value={entry}
            onClick={(e) => {
                e.preventDefault()
                onCommit(entry)
            }}
            data-slot="taxonomic-filter-menu-row"
            className={cn(
                'flex flex-row items-center gap-2 rounded-sm px-2 py-1 cursor-pointer outline-none',
                // `data-selected` mirrors base-ui's `highlighted` state via
                // the render fn below — keyboard / pointer cursor on this
                // row gets a soft hover tint.
                'data-[selected]:bg-[var(--fill-hover)]',
                // Persistent tint for the committed selection. Plain
                // conditional class — base-ui's `render` override only
                // forwards its own computed props, so `data-*` extras
                // passed to `Autocomplete.Item` would be dropped.
                isSelected && 'bg-[var(--fill-hover)]'
            )}
            // `id` lives on the rendered `<div>` (not on the Autocomplete.Item
            // props) — base-ui omits `id` from its prop typing because it
            // assigns its own. The wrap-render lets us pin the stable id
            // we need for `scrollIntoView` + checkmark lookups without
            // fighting the type.
            render={(itemProps, state) => (
                <div {...itemProps} id={stableId} data-selected={state.highlighted ? '' : undefined} />
            )}
        >
            <div className="flex flex-col items-start gap-0 min-w-0 flex-1">
                <span className="text-sm leading-tight truncate max-w-full">{name}</span>

                <span className="font-mono text-xs text-tertiary/50 leading-tight truncate max-w-full">
                    {value || <span className="opacity-50">N/A</span>}
                </span>
                {showCategory && <MenuLabel className="text-tertiary/50 text-xxs p-0 mt-px">{category}</MenuLabel>}
            </div>
            {isSelected && <Check className="size-3.5 text-foreground shrink-0" />}
            {opensSubmenu && <ChevronRight className="size-3.5 text-tertiary shrink-0" />}
        </Autocomplete.Item>
    )
}

interface ChipButtonProps {
    label: string
    active: boolean
    onSelect: () => void
}

function ChipButton({ label, active, onSelect }: ChipButtonProps): JSX.Element {
    return (
        <Button
            type="button"
            role="tab"
            size="sm"
            aria-selected={active}
            variant={active ? 'primary' : 'outline'}
            onMouseDown={(e: React.MouseEvent<HTMLButtonElement>) => e.preventDefault()}
            onClick={onSelect}
        >
            {label}
        </Button>
    )
}

/**
 * Zero-DOM fetcher: runs `useGroupList` for one group and reports items
 * up via callback. Mounting one per visible group keeps the parent memo
 * cheap (no nested hook arrays).
 */
function Fetcher({
    group,
    onItems,
}: {
    group: TaxonomicFilterGroup
    onItems: (type: string, items: TaxonomicDefinitionTypes[]) => void
}): null {
    const { getGroupListInput } = useTaxonomicFilterContext()
    const list = useGroupList(getGroupListInput(group))
    useEffect(() => {
        onItems(group.type, list.items)
    }, [group.type, list.items, onItems])
    return null
}

/**
 * Parse a URL-shaped string into `{ host, pathTail }` for two-line row
 * rendering. Returns `null` for anything that isn't a `http(s)://` URL or
 * fails to parse — caller falls back to default rendering.
 */
function parseUrl(s: string): { host: string; pathTail: string } | null {
    if (typeof s !== 'string' || !/^https?:\/\//i.test(s)) {
        return null
    }
    try {
        const u = new URL(s)
        const tail = (u.pathname || '/') + u.search + u.hash
        return { host: u.host, pathTail: tail }
    } catch {
        return null
    }
}

function getRawName(item: TaxonomicDefinitionTypes, group: TaxonomicFilterGroup): string {
    // Prefer the underlying `name` field — it's the raw identifier on
    // most definitions (`$timestamp`, `event`, `properties.$browser`).
    // Some groups override `getName` to return a humanized label (Event
    // metadata maps `id` → `coreFilterDefinition.label`, returning
    // "Timestamp" for `timestamp`); falling back to `getName` only when
    // the item has no `name` keeps the raw → friendly → display chain
    // working so the preview's "Sent as" surfaces the underlying key.
    const itemName = (item as unknown as { name?: unknown }).name
    if (typeof itemName === 'string' && itemName.length > 0) {
        return itemName
    }
    return group.getName?.(item) ?? ''
}

function getFriendlyLabel(item: TaxonomicDefinitionTypes, group: TaxonomicFilterGroup): string | undefined {
    const raw = getRawName(item, group)
    if (!raw) {
        return undefined
    }
    return getCoreFilterDefinition(raw, group.type)?.label
}
