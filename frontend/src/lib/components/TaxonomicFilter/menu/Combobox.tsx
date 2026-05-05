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
    TaxonomicFilterGroupType.SuggestedFilters,
    TaxonomicFilterGroupType.RecentFilters,
    TaxonomicFilterGroupType.PinnedFilters,
    TaxonomicFilterGroupType.DataWarehouse,
    TaxonomicFilterGroupType.HogQLExpression,
])

export interface MenuFilterComboboxProps {
    drillTo: DrillCategory
    /** Pre-resolved entries for `drillTo='recent' | 'pinned'`. Skips fetching. */
    drillItems?: MenuFilterEntry[]
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
    const [highlightedEntry, setHighlightedEntry] = useState<MenuFilterEntry | null>(null)
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
        if (scope === 'recent' || scope === 'pinned') {
            return [] // items come from `drillItems`
        }
        const g = groups.find((gr) => gr.type === scope)
        return g ? [g] : []
    }, [showChips, activeChip, drillTo, groups, visibleChipGroups])

    // Indexed entries — flat list across all visible groups (or
    // pre-resolved `drillItems` for recent/pinned).
    const indexed = useMemo<MenuFilterEntry[]>(() => {
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
        return merged
    }, [drillItems, targetGroups, itemsByType])

    const filtered = useMemo<MenuFilterEntry[]>(() => {
        const q = searchQuery.trim()
        if (!q) {
            return indexed
        }
        const fuse = new FuseClass(indexed, FUSE_OPTIONS as any)
        return fuse.search(q).map((r) => r.item)
    }, [indexed, searchQuery])

    const headerTitle =
        title ??
        (drillTo === 'all'
            ? 'Choose filter'
            : drillTo === 'recent'
              ? 'Recent'
              : drillTo === 'pinned'
                ? 'Pinned'
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
            const ordered: DrillCategory[] = ['all', ...visibleChipGroups.map((g) => g.type)]
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
            <MenuFilterHeader title={headerTitle} onBack={onBack} />
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
                                            placeholder={placeholder ?? 'Search…'}
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
                        <ScrollArea className="flex-1 min-h-0 scroll-py-8" showScrollToButton={['bottom']}>
                            <Autocomplete.List data-quill className="p-2 scroll-py-8">
                                <Autocomplete.Empty className="px-2 py-3 text-xs text-secondary empty:hidden">
                                    {filtered.length === 0 && searchQuery
                                        ? 'No matches'
                                        : filtered.length === 0
                                          ? 'No items'
                                          : null}
                                </Autocomplete.Empty>
                                <Autocomplete.Collection>
                                    {(entry: MenuFilterEntry) => (
                                        <Row
                                            entry={entry}
                                            showGroupLabel={activeChip === 'all'}
                                            showGroupSubtitle={drillTo === 'recent' || drillTo === 'pinned'}
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
    /** Render the group's name on its own line (mixed-group views only). */
    showGroupLabel: boolean
    /** Replace the raw-name subtitle with the source group name. */
    showGroupSubtitle?: boolean
    /** Show a trailing chevron when click drills to another panel (DWH config). */
    opensSubmenu?: boolean
    /** DOM id of the currently-selected row (for the trailing checkmark). */
    selectedRowId?: string | null
    onCommit: CommitFn
}

function Row({ entry, showGroupLabel, showGroupSubtitle, opensSubmenu, selectedRowId, onCommit }: RowProps): JSX.Element {
    const { item, group } = entry
    const friendly = entry.friendlyLabel
    // URL detection — if the row's name parses as a URL, show the path
    // (everything after the TLD) on line one and the host on line two so
    // long URLs stay readable.
    const url = parseUrl(entry.name)
    const title = url ? url.pathTail : friendly && friendly.length > 0 ? friendly : entry.name
    // Subtitle precedence: URL host wins; then group name (Recent/Pinned
    // need the source group as context); then the raw `$value` when it
    // differs from the friendly title; otherwise omitted.
    const subtitle = url
        ? url.host
        : showGroupSubtitle
          ? group.name
          : friendly && friendly !== entry.name
            ? entry.name
            : undefined
    const stableId = `menu-filter-row-${group.type}-${String(group.getValue?.(item) ?? entry.name)}`
    const isSelected = selectedRowId === stableId
    return (
        <Autocomplete.Item
            id={stableId}
            value={entry}
            data-checked={isSelected || undefined}
            onClick={(e) => {
                e.preventDefault()
                onCommit(entry)
            }}
            className={cn(
                'flex flex-row items-center gap-2 rounded-sm px-2 py-1 cursor-pointer outline-none',
                // `data-selected` mirrors base-ui's `highlighted` state via
                // the render fn below — keyboard / pointer cursor on this
                // row gets a soft hover tint.
                'data-[selected]:bg-[var(--fill-hover)]',
            )}
            render={(itemProps, state) => (
                <div
                    {...itemProps}
                    data-selected={state.highlighted ? '' : undefined}
                />
            )}
        >
            <div className="flex flex-col items-start gap-0 min-w-0 flex-1">
                <span className="text-sm leading-tight truncate max-w-full">{title}</span>
                {subtitle && (
                    <span className="text-xs text-tertiary/50 leading-tight truncate max-w-full">{subtitle}</span>
                )}
                {showGroupLabel && <MenuLabel className="text-tertiary/50 text-xxs p-0 mt-px">{group.name}</MenuLabel>}
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
