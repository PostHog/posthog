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
import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconCheck, IconChevronRight, IconClock, IconPinFilled } from '@posthog/icons'
import {
    Badge,
    Button,
    cn,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    MenuLabel,
    ScrollArea,
    Select,
    SelectContent,
    SelectGroup,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Separator,
    Skeleton,
} from '@posthog/quill'

import { createFuse } from 'lib/utils/fuseSearch'
import { surveyQuestionLabelsLogic } from 'scenes/surveys/surveyQuestionLabelsLogic'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { useTaxonomicFilterContext } from '../headless/context'
import { useGroupList } from '../hooks/useGroupList'
import { TaxonomicDefinitionTypes, TaxonomicFilterGroup, TaxonomicFilterGroupType } from '../types'
import { COLLAPSED_TO_CONTAINS_ROW, urlContainsRowLabel } from '../utils/collapsedContainsRow'
import { promoteMatchingBy } from '../utils/promoteProperties'
import { MenuFilterHeader } from './Header'
import { PreviewPane } from './PreviewPane'
import { CommitFn, CommitSelectionContext, DrillCategory, MenuFilterEntry, TAXONOMIC_FILTER_SURFACE } from './types'
import { VerificationBadge } from './VerificationBadge'

// `threshold` + `ignoreDiacritics` come from `createFuse` defaults; we
// only override what's specific to the menu (keys + the
// `ignoreLocation` switch so a typo near the end of the string still
// matches).
const FUSE_OPTIONS = {
    keys: ['name', 'friendlyLabel', 'recentLabel'],
    ignoreLocation: true,
}

/** Categories filtered out of the chip row when drillTo === 'all'. */
const HIDDEN_FROM_CHIPS: ReadonlySet<TaxonomicFilterGroupType> = new Set([
    // `SuggestedFilters` from taxonomicFilterLogic is a tiny set of
    // primary-property promotions for the *currently-selected event* +
    // autocapture text/selector. It's empty for almost every flow that
    // doesn't have an event-in-context, and even when populated it
    // duplicates what shows up under Event properties. Hide entirely;
    // recents/pinned now lead the "All" surface directly.
    TaxonomicFilterGroupType.SuggestedFilters,
    // RecentFilters / PinnedFilters surface via the dropdown menu
    // (Recent / Pinned entries with chevrons) and lead the "All" surface;
    // DataWarehouse + HogQL expression have their own dedicated panels —
    // none of them belong in the in-combobox chip row.
    TaxonomicFilterGroupType.RecentFilters,
    TaxonomicFilterGroupType.PinnedFilters,
    TaxonomicFilterGroupType.DataWarehouse,
    TaxonomicFilterGroupType.HogQLExpression,
])

/** How many recents and pinned each lead the default "All" surface, matching
 *  the pill variant's top-3 face. */
const RECENT_PINNED_PREFIX_LIMIT = 3

/** Fallback that opens the reveal barrier even if some group's fetch never
 *  settles. Matches the legacy `taxonomicFilterLogic` value. */
const REVEAL_BARRIER_TIMEOUT_MS = 5000

/** Stable empty list so a held (barrier-closed) render keeps a constant
 *  `items` identity instead of allocating a new array each time. */
const NO_ENTRIES: MenuFilterEntry[] = []

/** Debounce before emitting `taxonomic_filter_search_query` — matches the
 *  legacy picker so the search telemetry is comparable across variants. */
export const SEARCH_QUERY_DEBOUNCE_MS = 500

/** Identity for an entry's underlying definition — source group + value.
 *  Uses `::` as separator to serve as a dedup key (distinct from DOM ids). */
function entryKey(entry: MenuFilterEntry): string {
    return `${entry.group.type}::${String(entry.group.getValue?.(entry.item) ?? entry.name)}${
        entry.recentPropertyFilter ? '::full' : ''
    }`
}

/** Stable DOM id for a menu row — used for scroll-into-view, checkmark
 *  lookups, and `aria-activedescendant`. The format must be identical
 *  everywhere it is constructed. */
function rowDomId(entry: MenuFilterEntry): string {
    return `menu-filter-row-${entry.group.type}-${String(entry.group.getValue?.(entry.item) ?? entry.name)}${
        entry.recentPropertyFilter ? '-full' : ''
    }`
}

function fuseMatchEntries(entries: MenuFilterEntry[], query: string): MenuFilterEntry[] {
    if (entries.length === 0) {
        return []
    }
    return createFuse(entries, FUSE_OPTIONS as Parameters<typeof createFuse<MenuFilterEntry>>[1])
        .search(query)
        .map((r) => r.item)
}

export interface MenuFilterComboboxProps {
    drillTo: DrillCategory
    /** Pre-resolved entries for `drillTo='recent' | 'pinned'`. Skips fetching. */
    drillItems?: MenuFilterEntry[]
    /** Recents/pinned (each resolved to its source group). Lead the default
     *  "All" surface: top-3 of each when idle, query matches when searching. */
    recentEntries?: MenuFilterEntry[]
    pinnedEntries?: MenuFilterEntry[]
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
    recentEntries,
    pinnedEntries,
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
        // Collapsed groups (e.g. Pageview URLs) aren't navigable categories, so a
        // selection from one lands on "All" — its row still surfaces there via the
        // selected-entry prepend — instead of stranding the user in a hidden scope.
        if (drillTo === 'all' && selectedEntry && !COLLAPSED_TO_CONTAINS_ROW.has(selectedEntry.group.type)) {
            return selectedEntry.group.type
        }
        return drillTo
    })
    // The scope the user is actually looking at: the active chip when chips show
    // (drillTo='all'), otherwise the drilled-to category. Single source for the
    // telemetry group type, empty state, stale-toggle gating, and reset trigger.
    const activeScope: DrillCategory = drillTo === 'all' ? activeChip : drillTo
    const [itemsByType, setItemsByType] = useState<Record<string, TaxonomicDefinitionTypes[]>>({})
    // Per-group loading flags reported up by `Fetcher`. We need this in the
    // parent so the empty-state vs. skeleton decision sees the freshest
    // fetch status across every visible (target) group, not just the one
    // whose `useGroupList` hook last rendered.
    const [loadingByType, setLoadingByType] = useState<Record<string, boolean>>({})
    // Per-group `isFetching` flags (true during background refetches too, unlike
    // `loadingByType` which is `loading && no-items-yet`). Drives the reveal
    // barrier so kept-previous-data refetches still hold the list.
    const [fetchingByType, setFetchingByType] = useState<Record<string, boolean>>({})
    // Reveal barrier (ported from the legacy `taxonomicFilterLogic`): on a fresh
    // search we hold the result list behind skeletons until every visible group's
    // fetch settles (or a 5s fallback), so slower groups don't render on top of a
    // stale/partial list and rows don't jump around. Mirrors `revealBarrierOpen`.
    const [revealBarrierOpen, setRevealBarrierOpen] = useState(true)
    const [barrierQuery, setBarrierQuery] = useState(searchQuery)
    // Seed the highlight with the committed selection so the preview
    // pane shows the right definition before any row hovers fire. Once
    // the list mounts, `autoHighlight="always"` + the reordered
    // `filtered` (selected entry promoted to index 0) keeps the
    // highlight on the same row.
    const [highlightedEntry, setHighlightedEntry] = useState<MenuFilterEntry | null>(selectedEntry ?? null)
    const inputRef = useRef<HTMLInputElement | null>(null)

    // Stale events (event definitions not ingested within the staleness window)
    // are hidden by default to match the legacy picker. The opt-in is per-search:
    // reset whenever the query or active scope changes so stale results never
    // carry across unrelated searches (mirrors legacy `setSearchQuery`/`setActiveTab`).
    const [includeStaleEvents, setIncludeStaleEvents] = useState(false)
    useEffect(() => {
        setIncludeStaleEvents(false)
    }, [searchQuery, activeScope])
    // Read inside the debounced search-query capture without re-triggering it on
    // toggle (the toggle changes results, not the query).
    const includeStaleEventsRef = useRef(includeStaleEvents)
    useEffect(() => {
        includeStaleEventsRef.current = includeStaleEvents
    }, [includeStaleEvents])

    // Stable DOM id for the selected row — derived via `rowDomId` to stay in
    // sync with `Row`'s `stableId` and the `filtered` selected-promotion logic.
    const selectedRowId = useMemo<string | null>(() => {
        if (!selectedEntry) {
            return null
        }
        return rowDomId(selectedEntry)
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

    const reportLoading = useCallback((type: string, loading: boolean): void => {
        setLoadingByType((prev) => (prev[type] === loading ? prev : { ...prev, [type]: loading }))
    }, [])

    const reportFetching = useCallback((type: string, fetching: boolean): void => {
        setFetchingByType((prev) => (prev[type] === fetching ? prev : { ...prev, [type]: fetching }))
    }, [])

    // Chips show only when `drillTo='all'` — drilled scopes lock to one
    // category and hide the chip row per spec.
    const showChips = drillTo === 'all'
    const visibleChipGroups = useMemo(() => groups.filter((g) => !HIDDEN_FROM_CHIPS.has(g.type)), [groups])

    // Ordered category list — drives the category dropdown and Tab cycling
    // (kept in sync so the dropdown trigger reflects the active scope).
    // Recent / Pinned lead the content categories (when present) so they're
    // navigable from the combobox the way the pill variant's category column
    // exposes them, not only via the outer dropdown menu.
    const categoryOptions = useMemo<{ value: DrillCategory; label: string }[]>(() => {
        const opts: { value: DrillCategory; label: string }[] = [{ value: 'all', label: 'All' }]
        if (recentEntries && recentEntries.length > 0) {
            opts.push({ value: 'recent', label: 'Recent' })
        }
        if (pinnedEntries && pinnedEntries.length > 0) {
            opts.push({ value: 'pinned', label: 'Pinned' })
        }
        for (const g of visibleChipGroups) {
            // Collapsed groups feed the "all" rows but aren't navigable categories.
            if (COLLAPSED_TO_CONTAINS_ROW.has(g.type)) {
                continue
            }
            opts.push({ value: g.type, label: g.name })
        }
        return opts
    }, [recentEntries, pinnedEntries, visibleChipGroups])

    // Resolve which groups feed the visible list, based on the active chip
    // (or the drill scope when chips are hidden).
    const targetGroups = useMemo<TaxonomicFilterGroup[]>(() => {
        if (activeScope === 'all') {
            return visibleChipGroups
        }
        if (activeScope === 'recent' || activeScope === 'pinned') {
            return [] // items come from `drillItems`
        }
        const g = groups.find((gr) => gr.type === activeScope)
        return g ? [g] : []
    }, [activeScope, groups, visibleChipGroups])

    // Mount + subscribe so `$survey_response_<question-id>` keys resolve to the
    // actual question text. `getFriendlyLabel` reads through `getCoreFilterDefinition`,
    // which falls back to a static label until `surveyQuestionLabelsLogic` has
    // loaded. Subscribing here ensures `indexed` recomputes the labels once they
    // arrive — without this, each entry's `friendlyLabel` would be frozen to the
    // pre-load fallback for the lifetime of the popover.
    const { surveyQuestionLabels } = useValues(surveyQuestionLabelsLogic)

    // Indexed entries — flat list across all visible groups (or
    // pre-resolved `drillItems` for recent/pinned).
    const indexed = useMemo<MenuFilterEntry[]>(() => {
        const scope = showChips ? activeChip : drillTo
        if (drillItems) {
            return drillItems
        }
        // Recent / Pinned scopes selected from the combobox dropdown read the
        // pre-resolved entries directly (the outer menu drill passes the same
        // lists via `drillItems`).
        if (scope === 'recent') {
            return recentEntries ?? []
        }
        if (scope === 'pinned') {
            return pinnedEntries ?? []
        }
        const merged: MenuFilterEntry[] = []
        const trimmedQuery = searchQuery.trim()
        for (const group of targetGroups) {
            const items = itemsByType[group.type] ?? []
            // Collapse to a single "URL contains <query>" row when the contains
            // search found at least one matching URL. The synthetic item's value
            // is the typed query (its `name`, since the group's getValue reads
            // `name`), so `selectItem`'s existing PageviewUrls branch commits
            // `$current_url IContains <query>`.
            if (COLLAPSED_TO_CONTAINS_ROW.has(group.type)) {
                if (trimmedQuery && items.length > 0) {
                    const label = urlContainsRowLabel(trimmedQuery)
                    merged.push({
                        // `isContainsShortcut` tags this synthetic row so the commit
                        // telemetry can measure adoption of the contains shortcut vs
                        // the old per-URL value-picker.
                        item: { name: trimmedQuery, isContainsShortcut: true } as unknown as TaxonomicDefinitionTypes,
                        group,
                        name: label,
                        friendlyLabel: label,
                    })
                }
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
        // Make sure the committed selection is reachable from the list
        // even when the remote endpoint paginated past it (limit=100,
        // alphabetical ordering — long-tail custom events get cut off
        // and the user can't see what they previously picked). Prepend
        // it if missing so it's clickable, scroll-able, and feeds the
        // preview pane. Skip when the active chip filters it out
        // (showing it under the wrong category would lie to the user).
        if (selectedEntry) {
            // `recent`/`pinned` scopes already returned above, so the only
            // mixed scope left here is `all`.
            const fitsScope = scope === 'all' || scope === selectedEntry.group.type
            if (fitsScope) {
                // Stringify both sides so a synthetic `selected` shimmed in
                // by callers like `TaxonomicPopoverMenu` (where the value
                // arrives as e.g. `'5'`) dedups against the real entry
                // returned by the endpoint (`cohort.id === 5`). Without this
                // coercion the two land side-by-side with two checkmarks —
                // the stableId path below already coerces, so matching here
                // keeps the prepend logic aligned with how rows are keyed.
                const selectedValue = String(selectedEntry.group.getValue?.(selectedEntry.item) ?? selectedEntry.name)
                const present = merged.some(
                    (e) =>
                        e.group.type === selectedEntry.group.type &&
                        String(e.group.getValue?.(e.item) ?? e.name) === selectedValue
                )
                if (!present) {
                    merged.unshift(selectedEntry)
                }
            }
        }
        return merged
        // `surveyQuestionLabels` is a deliberate recompute trigger: it isn't read
        // directly in the body, but `getFriendlyLabel` → `getCoreFilterDefinition`
        // reads its value via `findMounted()`. Without this dep the memo would
        // freeze each entry's `friendlyLabel` to the pre-load fallback.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        drillItems,
        recentEntries,
        pinnedEntries,
        targetGroups,
        itemsByType,
        selectedEntry,
        showChips,
        activeChip,
        drillTo,
        searchQuery,
        surveyQuestionLabels,
    ])

    // Recents + pinned that lead the default "All" surface (fixed order:
    // recents, then pinned). Idle shows the top-3 of each; searching shows the
    // query matches. Computed outside `filtered` so the endpoint-passthrough
    // there can't re-introduce a non-matching endpoint-backed recent.
    const recentsPinnedPrefix = useMemo<MenuFilterEntry[]>(() => {
        const scope = showChips ? activeChip : drillTo
        if (scope !== 'all') {
            return []
        }
        const recents = recentEntries ?? []
        const pinned = pinnedEntries ?? []
        const q = searchQuery.trim()
        const recentSegment = q ? fuseMatchEntries(recents, q) : recents.slice(0, RECENT_PINNED_PREFIX_LIMIT)
        const recentSegmentKeys = new Set(recentSegment.map(entryKey))
        const pinnedPool = (q ? fuseMatchEntries(pinned, q) : pinned).filter((e) => !recentSegmentKeys.has(entryKey(e)))
        const pinnedSegment = q ? pinnedPool : pinnedPool.slice(0, RECENT_PINNED_PREFIX_LIMIT)
        return [...recentSegment, ...pinnedSegment]
    }, [showChips, activeChip, drillTo, recentEntries, pinnedEntries, searchQuery])

    // Recency lookup so any row that is one of the user's recents/pinned gets a
    // "- recent" / "- pinned" tag on its category label, wherever it appears
    // (matching the pill variant's per-row source tags).
    const recentKeys = useMemo(() => new Set((recentEntries ?? []).map(entryKey)), [recentEntries])
    const pinnedKeys = useMemo(() => new Set((pinnedEntries ?? []).map(entryKey)), [pinnedEntries])
    const recencyForEntry = useCallback(
        (entry: MenuFilterEntry): 'recent' | 'pinned' | null => {
            const key = entryKey(entry)
            if (recentKeys.has(key)) {
                return 'recent'
            }
            if (pinnedKeys.has(key)) {
                return 'pinned'
            }
            return null
        },
        [recentKeys, pinnedKeys]
    )

    const filtered = useMemo<MenuFilterEntry[]>(() => {
        const q = searchQuery.trim()
        let base: MenuFilterEntry[]
        if (!q) {
            base = indexed
        } else {
            // The endpoint is the search authority for endpoint-backed
            // groups (e.g. Cohorts use `name__icontains` server-side, plus
            // server-side behavioral-cohort exclusion). Re-running the
            // client Fuse over already-server-searched results filters them
            // a *second*, fuzzier time — and Fuse scoring isn't monotonic as
            // the query grows, so a valid match shown for "posthog te" can
            // vanish at "posthog team". So only Fuse locally-sourced groups
            // (Actions, etc., which load their full list client-side); pass
            // server-searched entries through untouched, preserving order.
            const localSourced = indexed.filter((e) => !e.group.endpoint)
            const localMatches =
                localSourced.length > 0
                    ? new Set(
                          createFuse(localSourced, FUSE_OPTIONS as Parameters<typeof createFuse<MenuFilterEntry>>[1])
                              .search(q)
                              .map((r) => r.item)
                      )
                    : null
            base = indexed.filter((e) => !!e.group.endpoint || (localMatches?.has(e) ?? false))
        }
        // Promote the committed selection to index 0 so base-ui's
        // `autoHighlight="always"` lands on it the moment the list
        // mounts — keyboard nav starts on the selected row, the
        // preview pane shows the right definition, and `Enter` re-commits
        // without forcing the user to scroll. Skip when the user has
        // typed a search query — relevance order should win there.
        if (!q && selectedRowId) {
            const idx = base.findIndex((e) => rowDomId(e) === selectedRowId)
            if (idx > 0) {
                base = [base[idx], ...base.slice(0, idx), ...base.slice(idx + 1)]
            }
        }
        // Default "All" surface leads with recents/pinned (fixed order), then
        // the cross-tab content with `email`/`url` promotion. Recents/pinned
        // stay above the content rows so users can learn the order.
        const scope = showChips ? activeChip : drillTo
        if (scope === 'all') {
            const prefixKeys = new Set(recentsPinnedPrefix.map(entryKey))
            const content = prefixKeys.size > 0 ? base.filter((e) => !prefixKeys.has(entryKey(e))) : base
            return [
                ...recentsPinnedPrefix,
                ...promoteMatchingBy(content, searchQuery, (e) => (e.item as { name?: string }).name ?? e.name),
            ]
        }
        return base
    }, [indexed, searchQuery, selectedRowId, recentsPinnedPrefix, showChips, activeChip, drillTo])

    // O(1) row -> rendered-position lookup, rebuilt with `filtered`. Avoids an
    // O(n) `indexOf` per commit and the stale-index risk if `filtered`'s identity
    // shifts between render and click.
    const positionByEntry = useMemo<Map<MenuFilterEntry, number>>(() => {
        const map = new Map<MenuFilterEntry, number>()
        filtered.forEach((entry, position) => map.set(entry, position))
        return map
    }, [filtered])

    // Active-chip-aware placeholder. When the user has narrowed to a
    // specific category, use that group's `searchPlaceholder` so the
    // input reflects the search scope ("Search events" vs. the broad
    // "Search events, actions, …").
    const activePlaceholder = useMemo(() => {
        if (activeChip === 'all') {
            return placeholder ?? 'Search…'
        }
        if (activeChip === 'recent' || activeChip === 'pinned') {
            return placeholder ?? 'Search…'
        }
        const group = groups.find((g) => g.type === activeChip)
        const phrase = group?.searchPlaceholder ?? group?.name?.toLowerCase()
        return phrase ? `Search ${phrase}…` : (placeholder ?? 'Search…')
    }, [activeChip, groups, placeholder])

    // True while any visible group is fetching its first page (or refetching
    // with no kept-previous-data) — drives the skeleton fallback so the user
    // doesn't see "No X found" before the request resolves. Drilled
    // scopes that read from pre-resolved `drillItems` never fetch and stay at
    // `false`.
    const isAnyLoading = useMemo(() => {
        if (drillItems) {
            return false
        }
        return targetGroups.some((g) => loadingByType[g.type])
    }, [drillItems, targetGroups, loadingByType])

    // ---- Reveal barrier ----------------------------------------------------
    // Only engages while actively searching a fetching scope. Recent/Pinned
    // drills read pre-resolved `drillItems` (no fetch) so they're never gated.
    const searching = !drillItems && !!searchQuery.trim()
    // Close synchronously the instant the query changes (React "adjust state
    // while rendering" pattern) so a stale list never paints between keystroke
    // and the fetch starting. Re-opens immediately for empty/drill scopes.
    if (searchQuery !== barrierQuery) {
        setBarrierQuery(searchQuery)
        setRevealBarrierOpen(!searching)
    }
    const anyFetching = useMemo(() => targetGroups.some((g) => fetchingByType[g.type]), [targetGroups, fetchingByType])
    // Open once every visible group has settled. Edge-triggered on results /
    // fetching changes (not the bare query change) so the close commit — where
    // the Fetchers haven't yet reported `isFetching` — can't open it early.
    // Mirrors legacy's `!anyGroupLoading` check after `infiniteListResultsReceived`.
    useEffect(() => {
        if (revealBarrierOpen || !searching) {
            return
        }
        if (!anyFetching) {
            setRevealBarrierOpen(true)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [itemsByType, fetchingByType])
    // 5s fallback so a wedged/never-settling fetch can't trap the list behind
    // skeletons forever. Re-armed on every fresh query.
    useEffect(() => {
        if (!searching) {
            return
        }
        const id = window.setTimeout(() => setRevealBarrierOpen(true), REVEAL_BARRIER_TIMEOUT_MS)
        return () => window.clearTimeout(id)
    }, [barrierQuery, searching])
    // While held, show skeletons in place of the (stale/partial) result list.
    const barrierClosed = searching && !revealBarrierOpen
    const displayedItems = barrierClosed ? NO_ENTRIES : filtered

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
        // Suppress empty-state copy while a remote fetch is in flight —
        // the skeleton fallback below takes its place so we don't flash
        // "No X found" before the response resolves.
        if (isAnyLoading) {
            return null
        }
        const singleGroup =
            activeScope !== 'all' && activeScope !== 'recent' && activeScope !== 'pinned'
                ? (groups.find((g) => g.type === activeScope) ?? null)
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
        const categoryLabel = singleGroup?.name ?? null
        if (trimmedLen > 0) {
            return {
                title: categoryLabel ? `No "${categoryLabel}" found` : 'No matches',
            }
        }
        return {
            title: categoryLabel ? `No "${categoryLabel}" found` : 'No items',
        }
    }, [filtered.length, activeScope, groups, searchQuery, isAnyLoading])

    // --- Telemetry parity ---------------------------------------------------
    // Emit the legacy `taxonomic filter *` contract so the rebuild is
    // comparable to the control/pill variants by feature-flag value (PostHog
    // auto-attaches the active flag to every event). The meta scopes
    // (all/recent/pinned) have no single source group, so groupType is
    // undefined there — matching how legacy reports the active content tab.
    const telemetryGroupType = useMemo<TaxonomicFilterGroupType | undefined>(() => {
        return activeScope === 'all' || activeScope === 'recent' || activeScope === 'pinned' ? undefined : activeScope
    }, [activeScope])

    const pastedCharsRef = useRef(0)

    // `taxonomic_filter_search_query` — debounced; `inputMode`/`pastedFraction`
    // distinguish typed vs pasted input. `excludeStale` mirrors legacy: stale events
    // are hidden by default (so it reads true at search time, since the per-search
    // opt-in resets on every query change).
    useEffect(() => {
        const trimmed = searchQuery.trim()
        if (!trimmed) {
            pastedCharsRef.current = 0
            return
        }
        const timer = setTimeout(() => {
            const pastedChars = pastedCharsRef.current
            pastedCharsRef.current = 0
            const totalLength = searchQuery.length
            // Mirrors the legacy `taxonomicFilterLogic` classifier (kept in sync until the legacy picker is retired).
            const inputMode = classifyInputMode(pastedChars, totalLength)
            posthog.capture('taxonomic_filter_search_query', {
                surface: TAXONOMIC_FILTER_SURFACE,
                searchQuery,
                groupType: telemetryGroupType,
                inputMode,
                pastedFraction: totalLength > 0 ? Math.min(1, pastedChars / totalLength) : 0,
                excludeStale: !includeStaleEventsRef.current,
            })
        }, SEARCH_QUERY_DEBOUNCE_MS)
        return () => clearTimeout(timer)
    }, [searchQuery, telemetryGroupType])

    // `taxonomic filter empty result` — once per scope+query when a real search
    // returns nothing. `emptyState.body` marks the "type more" prompt, which is
    // not an empty result.
    // `groupType` is `undefined` for the meta scopes (All/Recent/Pinned) because there's no single content group there
    // (legacy fires per-group).
    // Dedup mirrors legacy `lastEmptyResultDedupeKey`: remember only the most
    // recent fired key so re-typing the same dead-end after an intervening query
    // re-fires (an unbounded set would under-count repeated dead-ends vs legacy).
    const lastEmptyResultKeyRef = useRef<string | null>(null)
    useEffect(() => {
        const trimmed = searchQuery.trim()
        if (!emptyState || emptyState.body || !trimmed) {
            return
        }
        const key = `${telemetryGroupType ?? 'all'}::${trimmed}`
        if (lastEmptyResultKeyRef.current === key) {
            return
        }
        lastEmptyResultKeyRef.current = key
        posthog.capture('taxonomic filter empty result', {
            surface: TAXONOMIC_FILTER_SURFACE,
            groupType: telemetryGroupType,
            searchQuery: trimmed,
        })
    }, [emptyState, searchQuery, telemetryGroupType])

    // Offered in the empty state whenever an event/custom-event group is among
    // the visible targets (drilled Events/CustomEvents, or the merged All surface
    // where stale events are also hidden) — mirrors legacy's recovery button:
    // no matches behind the default stale filter -> let the user opt in and
    // refetch with stale definitions included.
    const eventGroupInScope = targetGroups.some(
        (g) => g.type === TaxonomicFilterGroupType.Events || g.type === TaxonomicFilterGroupType.CustomEvents
    )
    const canOfferStaleToggle = !includeStaleEvents && !!searchQuery.trim() && eventGroupInScope
    const handleIncludeStaleEvents = useCallback((): void => {
        setIncludeStaleEvents(true)
        posthog.capture('taxonomic filter include stale toggled', {
            surface: TAXONOMIC_FILTER_SURFACE,
            includeStaleEvents: true,
            groupType: telemetryGroupType,
            searchQuery: searchQuery || undefined,
        })
    }, [telemetryGroupType, searchQuery])

    // Only the active scope's groups are fetched, so a narrowed-to-one-category search
    // that comes up empty can't know whether other categories have matches. Offer a jump
    // to "All" (which fetches every group) so the user can check without re-typing. This is a
    // deliberate divergence from the legacy `InfiniteList` empty state, which can read the
    // aggregated count (`allSectionHasResults`) and only offers the jump when All has matches.
    const canOfferAllSwitch =
        showChips &&
        !!searchQuery.trim() &&
        activeScope !== 'all' &&
        activeScope !== 'recent' &&
        activeScope !== 'pinned'
    const handleCheckOtherCategories = useCallback((): void => {
        posthog.capture('taxonomic filter menu category changed', {
            fromChip: activeChip,
            toChip: 'all',
            via: 'empty-state',
        })
        setActiveChip('all')
        inputRef.current?.focus()
    }, [activeChip])

    const selectionContextFor = useCallback(
        (entry: MenuFilterEntry): CommitSelectionContext => {
            const key = entryKey(entry)
            return {
                groupType: telemetryGroupType,
                // Rendered-row index; absent (not a sentinel) if the entry somehow
                // isn't in `filtered` — `position` then drops out of the payload.
                position: positionByEntry.get(entry),
                wasFromRecents: recentKeys.has(key),
                wasFromPinnedList: pinnedKeys.has(key),
            }
        },
        [telemetryGroupType, recentKeys, pinnedKeys, positionByEntry]
    )

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
            // Cycle categories while focus stays on input. Wraps both
            // directions. Shares `categoryOptions` with the dropdown so the
            // trigger label stays in sync.
            const ordered = categoryOptions.map((o) => o.value)
            const idx = ordered.indexOf(activeChip)
            const dir = e.shiftKey ? -1 : 1
            const next = ordered[(idx + dir + ordered.length) % ordered.length]
            posthog.capture('taxonomic filter menu category changed', {
                fromChip: activeChip,
                toChip: next,
                via: 'tab',
                direction: e.shiftKey ? 'backward' : 'forward',
            })
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
                items={displayedItems}
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
                                            onPaste={(e: React.ClipboardEvent<HTMLInputElement>) => {
                                                pastedCharsRef.current += e.clipboardData.getData('text').length
                                            }}
                                        />
                                    }
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                />
                                {/* Category dropdown — trailing addon. Picks
                                    the active scope; replaces the old
                                    flex-wrapped chip row. Only shown when
                                    there's more than the implicit "All"
                                    category to choose between. */}
                                {showChips && categoryOptions.length > 1 && (
                                    <InputGroupAddon align="inline-end">
                                        <Select<DrillCategory>
                                            value={activeChip}
                                            onValueChange={(value) => {
                                                posthog.capture('taxonomic filter menu category changed', {
                                                    fromChip: activeChip,
                                                    toChip: value ?? 'all',
                                                    via: 'dropdown',
                                                })
                                                setActiveChip(value ?? 'all')
                                                inputRef.current?.focus()
                                            }}
                                            itemToStringLabel={(value) =>
                                                categoryOptions.find((o) => o.value === value)?.label ?? 'All'
                                            }
                                        >
                                            <SelectTrigger
                                                size="sm"
                                                aria-label="Filter category"
                                                data-attr="menu-filter-category"
                                                className="mr-0.5"
                                            >
                                                <SelectValue />
                                            </SelectTrigger>
                                            {/* Fit the list to its items: at least as wide as the
                                                trigger, grow to the longest option, capped at the
                                                available viewport width so it never overflows. */}
                                            <SelectContent
                                                align="end"
                                                alignItemWithTrigger={false}
                                                className="w-max min-w-(--anchor-width) max-w-(--available-width)"
                                            >
                                                <SelectGroup>
                                                    {categoryOptions.map((o) => (
                                                        <SelectItem key={o.value} value={o.value}>
                                                            {o.label}
                                                        </SelectItem>
                                                    ))}
                                                </SelectGroup>
                                            </SelectContent>
                                        </Select>
                                    </InputGroupAddon>
                                )}
                            </InputGroup>
                        </div>
                        {!drillItems &&
                            targetGroups.map((g) => (
                                <Fetcher
                                    key={g.type}
                                    group={g}
                                    excludeStale={!includeStaleEvents}
                                    onItems={reportItems}
                                    onLoadingChange={reportLoading}
                                    onFetchingChange={reportFetching}
                                />
                            ))}
                        <ScrollArea className="flex-1 min-h-0 scroll-py-8" alwaysShowScrollbars>
                            <Autocomplete.List data-quill className="p-2 scroll-py-8">
                                <Autocomplete.Empty className="empty:hidden">
                                    {isAnyLoading || barrierClosed ? (
                                        <LoadingRows />
                                    ) : (
                                        emptyState && (
                                            <div
                                                data-attr="menu-filter-empty"
                                                className="flex flex-col items-center gap-2 px-4 py-8 text-center"
                                            >
                                                <div className="text-sm font-semibold">{emptyState.title}</div>
                                                {emptyState.body && (
                                                    <div className="text-xs text-secondary leading-relaxed">
                                                        {emptyState.body}
                                                    </div>
                                                )}
                                                {canOfferStaleToggle && !emptyState.body && (
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        data-attr="menu-filter-include-stale-events"
                                                        onClick={handleIncludeStaleEvents}
                                                    >
                                                        Include stale events
                                                    </Button>
                                                )}
                                                {canOfferAllSwitch && !emptyState.body && (
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        data-attr="menu-filter-check-other-categories"
                                                        onClick={handleCheckOtherCategories}
                                                    >
                                                        Check for results in other categories
                                                    </Button>
                                                )}
                                            </div>
                                        )
                                    )}
                                </Autocomplete.Empty>
                                <Autocomplete.Collection>
                                    {(entry: MenuFilterEntry) => (
                                        <Row
                                            entry={entry}
                                            // Show the category label on mixed-group views (All,
                                            // Recent, Pinned) — those mix items from multiple
                                            // categories so the label disambiguates. Drilled-to-
                                            // one-group views skip it (the panel header / chip
                                            // already names the category).
                                            showCategory={
                                                activeChip === 'all' ||
                                                activeChip === 'recent' ||
                                                activeChip === 'pinned' ||
                                                drillTo === 'recent' ||
                                                drillTo === 'pinned'
                                            }
                                            // Tag rows that are one of the user's recents/pinned so
                                            // they read e.g. "Events - recent".
                                            recency={recencyForEntry(entry)}
                                            // DWH rows open the column-config
                                            // form, not a final selection —
                                            // signal that with a chevron.
                                            opensSubmenu={drillTo === TaxonomicFilterGroupType.DataWarehouse}
                                            selectedRowId={selectedRowId}
                                            onSelect={() => onCommit(entry, undefined, selectionContextFor(entry))}
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
    /** When the row is one of the user's recents/pinned, append the source tag (e.g. "Events - recent"). */
    recency?: 'recent' | 'pinned' | null
    /** Show a trailing chevron when click drills to another panel (DWH config). */
    opensSubmenu?: boolean
    /** DOM id of the currently-selected row (for the trailing checkmark). */
    selectedRowId?: string | null
    /** Commit this row (also fires item-selected telemetry). */
    onSelect: () => void
}

/**
 * Resolve a row's normalized cells:
 *   - name:     human-friendly label (e.g. "Pageview", "/checkout")
 *   - value:    raw underlying value when distinct from the name (the full
 *               URL, or the raw `$key`). The preview pane is the primary home
 *               for this ("Sent as"), but the preview is hidden below `md`, so
 *               the row keeps a narrow-screen-only copy of it.
 *   - category: group name shown as an uppercase tag at the bottom
 *
 * URLs surface their path tail as the name; friendly definitions surface
 * the friendly label; everything else uses the entry name and has no
 * distinct raw value to show.
 */
function resolveRowCells(entry: MenuFilterEntry): { name: string; value?: string; category: string } {
    if (entry.recentLabel) {
        return { name: entry.recentLabel, category: entry.group.name }
    }
    const friendly = entry.friendlyLabel
    const pathTail = parseUrlPathTail(entry.name)
    if (pathTail !== null) {
        return { name: pathTail, value: entry.name, category: entry.group.name }
    }
    if (friendly && friendly.length > 0 && friendly !== entry.name) {
        return { name: friendly, value: entry.name, category: entry.group.name }
    }
    return { name: entry.name, category: entry.group.name }
}

function Row({ entry, showCategory, recency, opensSubmenu, selectedRowId, onSelect }: RowProps): JSX.Element {
    const { name, value, category } = resolveRowCells(entry)
    const stableId = rowDomId(entry)
    const isSelected = selectedRowId === stableId
    return (
        <Autocomplete.Item
            value={entry}
            onClick={(e) => {
                e.preventDefault()
                onSelect()
            }}
            data-slot="taxonomic-filter-menu-row"
            className={cn(
                'flex flex-row items-center gap-2 rounded-sm px-2 py-1 cursor-pointer outline-none',
                // `data-selected` mirrors base-ui's `highlighted` state via
                // the render fn below — keyboard / pointer cursor on this
                // row gets a soft hover tint.
                'data-selected:bg-(--fill-hover)',
                // Persistent tint for the committed selection. Plain
                // conditional class — base-ui's `render` override only
                // forwards its own computed props, so `data-*` extras
                // passed to `Autocomplete.Item` would be dropped.
                isSelected && 'bg-(--fill-hover)'
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
                {/* The preview pane (hidden below `md`) is the primary home for the
                    raw value, so only narrow screens keep it inline on the row. */}
                {value && (
                    <span className="md:hidden font-mono text-xs text-tertiary/50 leading-tight truncate max-w-full">
                        {value}
                    </span>
                )}
                {showCategory && <MenuLabel className="text-tertiary/50 text-xxs p-0 mt-px">{category}</MenuLabel>}
            </div>
            {recency && (
                <Badge variant="default" className="gap-1 shrink-0">
                    {recency === 'recent' ? <IconClock className="size-3" /> : <IconPinFilled className="size-3" />}
                    {recency === 'recent' ? 'Recent' : 'Pinned'}
                </Badge>
            )}
            <VerificationBadge entry={entry} />
            {isSelected && <IconCheck className="size-3.5 text-foreground shrink-0" />}
            {opensSubmenu && <IconChevronRight className="size-3.5 text-tertiary shrink-0" />}
        </Autocomplete.Item>
    )
}

/**
 * Zero-DOM fetcher: runs `useGroupList` for one group and reports items
 * up via callback. Mounting one per visible group keeps the parent memo
 * cheap (no nested hook arrays).
 */
function Fetcher({
    group,
    excludeStale,
    onItems,
    onLoadingChange,
    onFetchingChange,
}: {
    group: TaxonomicFilterGroup
    /** Hide stale event definitions (event / custom-event groups only). */
    excludeStale: boolean
    onItems: (type: string, items: TaxonomicDefinitionTypes[]) => void
    /** Reports `isLoading` (no items yet) so the parent can show a skeleton
     *  instead of "No X found" during the first fetch. */
    onLoadingChange: (type: string, loading: boolean) => void
    /** Reports `isFetching` (true during background refetches too) so the
     *  parent's reveal barrier holds the list until every group settles. */
    onFetchingChange: (type: string, fetching: boolean) => void
}): null {
    const { getGroupListInput } = useTaxonomicFilterContext()
    const list = useGroupList({ ...getGroupListInput(group), excludeStale })
    useEffect(() => {
        onItems(group.type, list.items)
    }, [group.type, list.items, onItems])
    useEffect(() => {
        onLoadingChange(group.type, list.showLoadingState)
    }, [group.type, list.showLoadingState, onLoadingChange])
    useEffect(() => {
        onFetchingChange(group.type, list.isFetching)
    }, [group.type, list.isFetching, onFetchingChange])
    // Make sure we flip back to "not loading"/"not fetching" when this group
    // unmounts — otherwise a stale `true` from a previously-active chip would
    // keep the skeleton (or the reveal barrier) stuck after we switch scope.
    useEffect(() => {
        return () => {
            onLoadingChange(group.type, false)
            onFetchingChange(group.type, false)
        }
    }, [group.type, onLoadingChange, onFetchingChange])
    return null
}

/** Skeleton placeholder shown in place of the result list while a remote
 *  fetch is in flight and we have nothing to show yet. Matches the
 *  single-line row layout so the popover height doesn't jump when results
 *  arrive. */
function LoadingRows(): JSX.Element {
    return (
        <div className="flex flex-col gap-1 p-2" data-attr="menu-filter-loading">
            {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} className="px-2 py-1">
                    <Skeleton className="h-3.5 w-2/3 rounded" />
                </div>
            ))}
        </div>
    )
}

/**
 * Parse a URL-shaped string into its path tail (path + search + hash) for
 * row rendering. Returns `null` for anything that isn't a `http(s)://` URL
 * or fails to parse — caller falls back to default rendering.
 */
function parseUrlPathTail(s: string): string | null {
    if (typeof s !== 'string' || !/^https?:\/\//i.test(s)) {
        return null
    }
    try {
        const u = new URL(s)
        return (u.pathname || '/') + u.search + u.hash
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

// Mirrors the legacy `taxonomicFilterLogic` classifier (kept in sync until the legacy picker is retired).
function classifyInputMode(pastedChars: number, totalLength: number): 'typed' | 'mixed' | 'pasted' {
    return pastedChars >= totalLength && pastedChars > 0 ? 'pasted' : pastedChars > 0 ? 'mixed' : 'typed'
}
