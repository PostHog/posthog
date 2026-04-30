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
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Button, cn, InputGroup, InputGroupInput, ScrollArea } from '@posthog/quill'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { useTaxonomicFilterContext } from '../headless/context'
import { useGroupList } from '../hooks/useGroupList'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../types'
import { MenuFilterHeader } from './Header'
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
}

export function MenuFilterCombobox({
    drillTo,
    drillItems,
    placeholder,
    onCommit,
    onBack,
    title,
}: MenuFilterComboboxProps): JSX.Element {
    const { groups } = useTaxonomicFilterContext()
    const [searchQuery, setSearchQuery] = useState('')
    const [activeChip, setActiveChip] = useState<DrillCategory>(drillTo)
    const [itemsByType, setItemsByType] = useState<Record<string, TaxonomicDefinitionTypes[]>>({})
    const inputRef = useRef<HTMLInputElement | null>(null)

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
                openOnInputClick={false}
                itemToStringValue={(entry: MenuFilterEntry) => entry.name}
            >
                <div className="flex flex-col flex-1 min-h-0">
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
                    {!drillItems && targetGroups.map((g) => <Fetcher key={g.type} group={g} onItems={reportItems} />)}
                    <ScrollArea className="flex-1 min-h-0" showScrollToButton={['bottom']}>
                        <Autocomplete.List data-quill className="p-2 scroll-py-1">
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
                                        // Recent/Pinned mix entries from many
                                        // groups — surface the source group as
                                        // a subtitle so the user can tell
                                        // `paid_bills` is a DWH table at a
                                        // glance.
                                        showGroupSubtitle={drillTo === 'recent' || drillTo === 'pinned'}
                                        onCommit={onCommit}
                                    />
                                )}
                            </Autocomplete.Collection>
                        </Autocomplete.List>
                    </ScrollArea>
                </div>
            </Autocomplete.Root>
        </div>
    )
}

interface RowProps {
    entry: MenuFilterEntry
    showGroupLabel: boolean
    /** Replace the raw-name subtitle with the source group name. */
    showGroupSubtitle?: boolean
    onCommit: CommitFn
}

function Row({ entry, showGroupLabel, showGroupSubtitle, onCommit }: RowProps): JSX.Element {
    const { item, group } = entry
    const friendly = entry.friendlyLabel
    const title = friendly && friendly.length > 0 ? friendly : entry.name
    const subtitle = showGroupSubtitle
        ? group.name
        : friendly && friendly !== entry.name
          ? entry.name
          : undefined
    const stableId = `menu-filter-row-${group.type}-${String(group.getValue?.(item) ?? entry.name)}`
    return (
        <Autocomplete.Item
            id={stableId}
            value={entry}
            onClick={(e) => {
                e.preventDefault()
                onCommit(entry)
            }}
            className={cn(
                'flex flex-col items-start gap-0 rounded-sm px-2 py-1 cursor-pointer outline-none',
                'data-[highlighted]:bg-[var(--fill-selected)]'
            )}
        >
            <span className="text-sm">
                {title}
                {showGroupLabel && (
                    <span className="ml-2 text-xxs uppercase tracking-wide text-secondary">{group.name}</span>
                )}
            </span>
            {subtitle && <span className="text-xs text-secondary">{subtitle}</span>}
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

function getRawName(item: TaxonomicDefinitionTypes, group: TaxonomicFilterGroup): string {
    return (
        group.getName?.(item) ??
        ('name' in (item as unknown as Record<string, unknown>)
            ? ((item as unknown as { name?: string }).name ?? '')
            : '')
    )
}

function getFriendlyLabel(item: TaxonomicDefinitionTypes, group: TaxonomicFilterGroup): string | undefined {
    const raw = getRawName(item, group)
    if (!raw) {
        return undefined
    }
    return getCoreFilterDefinition(raw, group.type)?.label
}
