/**
 * Dropdown-menu-fronted taxonomic filter.
 *
 * See `../headless/UX_SPEC.md` for the design.
 *
 * Architecture:
 *   - One state machine at the top (`MenuFilterState`).
 *   - Trigger button is anchor for both the dropdown menu (small list
 *     options) and the popover (data panels). The DropdownMenuTrigger
 *     is the visible button; PopoverTrigger is a transparent overlay
 *     used solely as a Floating UI anchor.
 *   - Popover dismiss treats clicks on the underlying trigger button as
 *     "outside" since the PopoverTrigger overlay isn't the click target.
 *     We cancel that specific outsidePress in `onOpenChange` so the
 *     popover doesn't immediately re-close when we route a `selected`
 *     user straight into a panel.
 *   - Each panel (Combobox / DwhConfig / HogQL) is a pure component; it
 *     receives data + callbacks.
 *
 * Consumer wraps it in `<TaxonomicFilterHeadless.Root>` so we can read
 * `groups` + `selectItem` via context (same orchestrator the legacy /
 * old headless components use).
 */
import { useValues } from 'kea'
import { ChevronRight } from 'lucide-react'
import posthog from 'posthog-js'
import { ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
    Button,
    cn,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@posthog/quill'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'

import { useTaxonomicFilterContext } from '../headless/context'
import { recentTaxonomicFiltersLogic } from '../recentTaxonomicFiltersLogic'
import { taxonomicFilterPinnedPropertiesLogic } from '../taxonomicFilterPinnedPropertiesLogic'
import { META_GROUP_TYPES, TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from '../types'
import { MenuFilterCombobox } from './Combobox'
import { MenuFilterDwhConfig } from './DwhFlow'
import { MenuFilterHogQLEditor } from './HogQLEditor'
import { CommitFn, DrillCategory, MenuFilterEntry, MenuFilterState, TaxonomicFilterGroup } from './types'

export interface TaxonomicFilterMenuProps {
    /** Default trigger label when nothing is selected. */
    triggerLabel?: string
    /** Currently-selected entry — drives the trigger label. Optional. */
    selected?: MenuFilterEntry | null
    /**
     * Trigger override. Static element or render function receiving
     * trigger state.
     */
    trigger?: ReactElement | ((state: TriggerState) => ReactElement)
    /** Called whenever the user commits a selection. */
    onCommit?: CommitFn
    /** Search input placeholder in the combobox. */
    placeholder?: string
    /**
     * Heading shown above the combobox panel. Defaults to "Choose filter".
     * Consumers like the series picker override this to read e.g.
     * "Choose series filter" so the panel matches its surrounding context.
     */
    comboboxTitle?: string
    /** Field tabs the DWH config form should expose (id_field, timestamp_field, …). Defaults to the standard bundle. */
    dataWarehousePopoverFields?: import('../types').DataWarehousePopoverField[]
    /** Insight context for the DWH config — when set, the aggregation-target tab reads `funnelDataLogic` for funnel-aware copy. */
    insightProps?: import('~/types').InsightLogicProps
}

export interface TriggerState {
    label: string
    selected: MenuFilterEntry | null
    open: boolean
}

export function TaxonomicFilterMenu({
    triggerLabel,
    selected,
    trigger,
    onCommit,
    placeholder,
    comboboxTitle,
    dataWarehousePopoverFields,
    insightProps,
}: TaxonomicFilterMenuProps): JSX.Element {
    const { groups, selectItem, inputProps, searchQuery } = useTaxonomicFilterContext()
    const [state, setState] = useState<MenuFilterState>({ kind: 'closed' })

    // Telemetry — track open dwell + commit funnel so we can compare
    // against legacy `taxonomic filter *` events. Stored in refs so the
    // close handler reads the actual session start, not a stale closure.
    const openedAtRef = useRef<number | null>(null)
    const hadCommitRef = useRef(false)
    const lastStateKindRef = useRef<MenuFilterState['kind']>('closed')
    useEffect(() => {
        const previous = lastStateKindRef.current
        const next = state.kind
        if (previous === 'closed' && next !== 'closed') {
            openedAtRef.current = Date.now()
            hadCommitRef.current = false
            posthog.capture('taxonomic filter menu opened', {
                openedTo: next,
                hadSelection: !!selected,
                triggerLabel,
            })
        } else if (previous !== 'closed' && next !== 'closed' && previous !== next) {
            posthog.capture('taxonomic filter menu drilled', {
                fromState: previous,
                toState: next,
            })
        } else if (previous !== 'closed' && next === 'closed') {
            posthog.capture('taxonomic filter menu closed', {
                dwellMs: openedAtRef.current ? Date.now() - openedAtRef.current : null,
                hadCommit: hadCommitRef.current,
                lastState: previous,
            })
            openedAtRef.current = null
        }
        lastStateKindRef.current = next
        // We deliberately don't track `selected` / `triggerLabel` — they
        // shouldn't fire fresh `opened` events on identity churn.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [state.kind])

    // -- Transitions -- single source of truth for state changes. Each
    // transition is a single setState call so React batches and there's
    // no intermediate flicker.
    const closeAll = useCallback(() => setState({ kind: 'closed' }), [])
    const openMenu = useCallback(() => setState({ kind: 'menu' }), [])
    const openCombobox = useCallback((drillTo: DrillCategory) => setState({ kind: 'combobox', drillTo }), [])
    const openDwhPick = useCallback(() => setState({ kind: 'dwh-pick' }), [])
    const openDwhConfig = useCallback(
        (table: TaxonomicDefinitionTypes, group: TaxonomicFilterGroup, origin: 'menu' | 'dwh-pick') =>
            setState({ kind: 'dwh-config', table, group, origin }),
        []
    )
    const openHogql = useCallback(() => setState({ kind: 'hogql-edit' }), [])

    /**
     * Resolve the initial state when the trigger opens. If `selected` is
     * set, jump straight into the panel that matches its group so the
     * user lands on something editable (e.g. the HogQL editor pre-filled
     * with the existing expression) instead of having to re-traverse the
     * dropdown menu. With no selection we fall back to the menu.
     */
    const resolveOpenState = useCallback((): MenuFilterState => {
        if (!selected) {
            return { kind: 'menu' }
        }
        if (selected.group.type === TaxonomicFilterGroupType.HogQLExpression) {
            return { kind: 'hogql-edit' }
        }
        if (selected.group.type === TaxonomicFilterGroupType.DataWarehouse) {
            // origin='menu' so X / Esc / Cancel return to the dropdown
            // menu rather than dropping the user into the (unscrolled)
            // dwh-pick list they never visited.
            return { kind: 'dwh-config', table: selected.item, group: selected.group, origin: 'menu' }
        }
        // Land on the regular combobox with chips visible — the matching
        // chip auto-selects via `selectedEntry` inside the combobox so the
        // user keeps full context and can switch categories without
        // bouncing back to the dropdown menu.
        return { kind: 'combobox', drillTo: 'all' }
    }, [selected])

    // -- Recent / Pinned shortcuts -- read from kea so menu items reflect
    // the live counts. Mapped back to entries via source group.
    const { recentFilterItems } = useValues(recentTaxonomicFiltersLogic)
    const { pinnedFilterItems } = useValues(taxonomicFilterPinnedPropertiesLogic)

    const recentEntries = useMemo<MenuFilterEntry[]>(
        () => mapShortcutItems(recentFilterItems as ShortcutItem[], groups),
        [recentFilterItems, groups]
    )
    const pinnedEntries = useMemo<MenuFilterEntry[]>(
        () => mapShortcutItems(pinnedFilterItems as ShortcutItem[], groups),
        [pinnedFilterItems, groups]
    )
    /*
     * Suggested = Recent ∪ Pinned across all groups, mirroring the
     * legacy popover's "Suggested step" view. Recent comes first
     * (chronologically more relevant to the user); pinned fills in
     * the curated picks. Dedup on `(group.type, value)` so a pinned
     * entry that's also recent only shows once. Each entry keeps its
     * source `group` reference so the row's category label still
     * reads "Events", "Actions", etc. (not "Suggested filters").
     */
    const suggestedEntries = useMemo<MenuFilterEntry[]>(() => {
        const seen = new Set<string>()
        const out: MenuFilterEntry[] = []
        for (const entry of [...recentEntries, ...pinnedEntries]) {
            const value = entry.group.getValue?.(entry.item) ?? entry.name
            const key = `${entry.group.type}::${String(value)}`
            if (seen.has(key)) {
                continue
            }
            seen.add(key)
            out.push(entry)
        }
        return out
    }, [recentEntries, pinnedEntries])

    const hasDwh = groups.some((g) => g.type === TaxonomicFilterGroupType.DataWarehouse)
    const hasHogql = groups.some((g) => g.type === TaxonomicFilterGroupType.HogQLExpression)

    // -- Commit -- routes through orchestrator's `selectItem` AND the
    // consumer's `onCommit` callback. Closes everything.
    const handleCommit = useCallback<CommitFn>(
        (entry, extra) => {
            const mergedItem = extra
                ? ({ ...(entry.item as unknown as object), ...extra } as unknown as TaxonomicDefinitionTypes)
                : entry.item
            const itemValue = entry.group.getValue?.(mergedItem) ?? null
            hadCommitRef.current = true
            posthog.capture('taxonomic filter menu item selected', {
                groupType: entry.group.type,
                hadSearchInput: !!searchQuery,
                query: searchQuery || undefined,
                hadExtras: !!extra,
                fromState: lastStateKindRef.current,
            })
            selectItem(entry.group, itemValue, mergedItem)
            onCommit?.({ ...entry, item: mergedItem }, extra)
            closeAll()
        },
        [selectItem, onCommit, closeAll, searchQuery]
    )

    // -- Trigger render --
    const label =
        (selected?.friendlyLabel && selected.friendlyLabel.length > 0 ? selected.friendlyLabel : selected?.name) ||
        triggerLabel ||
        inputProps.placeholder ||
        'Filter'
    const triggerState: TriggerState = { label, selected: selected ?? null, open: state.kind !== 'closed' }
    const triggerEl: ReactElement =
        typeof trigger === 'function' ? trigger(triggerState) : (trigger ?? <Button variant="outline">{label}</Button>)

    // -- Popover open derives from state. The dropdown menu is a separate
    // overlay (DropdownMenu); the popover is open for any non-menu,
    // non-closed kind.
    //
    // `dwh-config` deliberately excluded — when the user opens the DWH
    // config dialog we close the popover (not just stack on top of it),
    // so PostHog's stock z-order (`--z-popover` > `--z-modal`) keeps
    // Selects inside the dialog above the modal as expected. Cancelling
    // the dialog returns to `dwh-pick` and the popover re-opens at the
    // table list.
    const popoverOpen = state.kind === 'combobox' || state.kind === 'dwh-pick' || state.kind === 'hogql-edit'

    // Manual outside-click handling. base-ui Popover's automatic dismiss
    // can't reliably distinguish a click on the visible trigger (the
    // DropdownMenuTrigger button) from a click outside, because its own
    // PopoverTrigger is a transparent overlay sibling. We cancel its
    // outsidePress / focusOut firings (see `onOpenChange` below) and
    // close manually here.
    //
    // The popover content lives in a portal and Quill's `PopoverContent`
    // doesn't forward refs, so we walk the click target's ancestors
    // looking for `[data-slot="popover-content"]` instead.
    const triggerWrapRef = useRef<HTMLSpanElement | null>(null)

    /*
     * Mount the popover inside the global `main-content-container`
     * layout host (defined in `Navigation.tsx`) instead of the default
     * `document.body` portal. CSS container queries
     * (`@container/main-content-container`) walk DOM ancestors only —
     * a portal to body breaks that chain, so chip-row hints and panel
     * widths that key off `@[720px]/main-content-container` fail to
     * resolve. Mounting inside the container restores ancestry and
     * the same Tailwind classes work inside the popover content.
     *
     * Resolved synchronously via a lazy `useState` initializer so the
     * value is available on the first render — base-ui's Portal reads
     * `container` once at mount time, and a `useEffect`-set ref
     * arrives one render too late, leaving the popover at `<body>`.
     */
    const [popoverContainer, setPopoverContainer] = useState<HTMLElement | null>(() =>
        typeof document !== 'undefined'
            ? (document.querySelector('.main-content-container') as HTMLElement | null)
            : null
    )
    useEffect(() => {
        // Tab-aware scenes can mount before the container element
        // exists (the layout shell renders top-down). Re-poll once on
        // mount so we still catch it after a brief delay.
        if (popoverContainer) {
            return undefined
        }
        const id = window.setTimeout(() => {
            const found = document.querySelector('.main-content-container') as HTMLElement | null
            if (found) {
                setPopoverContainer(found)
            }
        }, 0)
        return () => window.clearTimeout(id)
    }, [popoverContainer])

    useEffect(() => {
        if (!popoverOpen) {
            return undefined
        }
        let attached = false
        const handler = (event: PointerEvent): void => {
            const target = event.target as Element | null
            if (!target) {
                return
            }
            // Treat clicks inside our own popover content as inside…
            if (target.closest?.('[data-slot="popover-content"]')) {
                return
            }
            // …and clicks inside ANY quill portal (Select dropdown, nested
            // DropdownMenu, ContextMenu, Combobox suggestions) as inside
            // too — those mount in their own portals at body level so a
            // raw `target.closest(popover-content)` misses them. Without
            // this, choosing a column from the field Select inside the
            // DWH config form was closing the whole popover.
            if (target.closest?.('[data-quill-portal]')) {
                return
            }
            if (triggerWrapRef.current?.contains(target)) {
                return
            }
            closeAll()
        }
        // Defer attach by one task — avoids catching the same click that
        // just transitioned us into a popover state.
        const timer = window.setTimeout(() => {
            attached = true
            document.addEventListener('pointerdown', handler, true)
        }, 0)
        return () => {
            window.clearTimeout(timer)
            if (attached) {
                document.removeEventListener('pointerdown', handler, true)
            }
        }
    }, [popoverOpen, closeAll])

    return (
        <DropdownMenu
            open={state.kind === 'menu'}
            onOpenChange={(open) => {
                if (open) {
                    // Trigger click is the only way DropdownMenu's
                    // onOpenChange(true) fires. Interpret it based on
                    // current state: closed → resolve to a panel; in a
                    // popover state → toggle the popover closed.
                    setState((current) => {
                        if (
                            current.kind === 'combobox' ||
                            current.kind === 'dwh-pick' ||
                            current.kind === 'dwh-config' ||
                            current.kind === 'hogql-edit'
                        ) {
                            return { kind: 'closed' }
                        }
                        return resolveOpenState()
                    })
                    return
                }
                // Functional setState — when a menu item's onClick already
                // advanced state (e.g. to 'combobox'), the subsequent menu
                // auto-close shouldn't yank us back to 'closed'. Use the
                // latest staged state, not the value from the render closure.
                setState((current) => (current.kind === 'menu' ? { kind: 'closed' } : current))
            }}
        >
            <Popover
                open={popoverOpen}
                onOpenChange={(open, eventDetails) => {
                    if (open) {
                        return
                    }
                    // Esc still closes via base-ui; everything else
                    // (outsidePress, focusOut, triggerHover, etc.) is
                    // unreliable when the trigger button isn't the
                    // PopoverTrigger element, so we cancel and let the
                    // document pointerdown effect handle it.
                    if (eventDetails.reason === 'escapeKey') {
                        closeAll()
                        return
                    }
                    eventDetails.cancel()
                }}
            >
                {/*
                 * `flex min-w-0 w-full` (not `inline-flex`) so the wrap
                 * fills its parent column instead of sizing to the
                 * trigger's intrinsic width. Without `min-w-0` the
                 * default `min-width: auto` makes the wrap grow to its
                 * content and overflow narrow parents — long filter
                 * names then bleed past the parity wrapper instead of
                 * truncating like the legacy trigger.
                 */}
                <span ref={triggerWrapRef} className="relative flex min-w-0 w-full">
                    <DropdownMenuTrigger render={triggerEl} data-attr="taxonomic-filter-menu-trigger" />
                    <PopoverTrigger
                        render={<span aria-hidden tabIndex={-1} className="absolute inset-0 pointer-events-none" />}
                    />
                </span>
                <PopoverContent
                    align="start"
                    side="bottom"
                    sideOffset={4}
                    container={popoverContainer}
                    className={cn(
                        'p-0 gap-0 overflow-hidden flex flex-col w-[calc(100%_-_2rem)] @[720px]/main-content-container:w-[720px] h-[400px]'
                    )}
                >
                    {state.kind === 'combobox' && (
                        <MenuFilterCombobox
                            drillTo={state.drillTo}
                            drillItems={
                                state.drillTo === 'recent'
                                    ? recentEntries
                                    : state.drillTo === 'pinned'
                                      ? pinnedEntries
                                      : state.drillTo === 'suggested'
                                        ? suggestedEntries
                                        : undefined
                            }
                            // Always pass `suggestedItems` so the chip
                            // works in 'all' mode too (without forcing a
                            // drill via the dropdown menu).
                            suggestedItems={suggestedEntries}
                            placeholder={placeholder ?? inputProps.placeholder}
                            // Only override the default "Choose filter"
                            // header when on the All chip — drilled views
                            // already title themselves with the group name.
                            title={state.drillTo === 'all' ? comboboxTitle : undefined}
                            selectedEntry={selected ?? null}
                            onCommit={handleCommit}
                            onBack={openMenu}
                        />
                    )}
                    {(state.kind === 'dwh-pick' || state.kind === 'dwh-config') && (
                        // Popover stays at the table list while the
                        // dwh-config Dialog (rendered below) is open on
                        // top — that way Cancel returns the user to the
                        // same list scroll/highlight position they were
                        // browsing before clicking a table.
                        <MenuFilterCombobox
                            drillTo={TaxonomicFilterGroupType.DataWarehouse}
                            title="Data warehouse tables"
                            placeholder="Search tables…"
                            selectedEntry={
                                selected?.group.type === TaxonomicFilterGroupType.DataWarehouse ? selected : null
                            }
                            onCommit={(entry) => openDwhConfig(entry.item, entry.group, 'dwh-pick')}
                            onBack={openMenu}
                        />
                    )}
                    {state.kind === 'hogql-edit' && (
                        <MenuFilterHogQLEditor
                            initialExpression={
                                selected?.group.type === TaxonomicFilterGroupType.HogQLExpression
                                    ? selected.name
                                    : undefined
                            }
                            onCommit={handleCommit}
                            onBack={openMenu}
                        />
                    )}
                </PopoverContent>
            </Popover>
            {/* DWH config dialog — sibling of the popover so it portals
                above it. Mounting only while in `dwh-config` state means
                the dialog auto-opens on transition and unmounts on
                close (Cancel / X / Esc → `onBack` returns to dwh-pick;
                Select calls `handleCommit` which triggers `closeAll`
                and dismisses both the dialog and the popover). */}
            {state.kind === 'dwh-config' && (
                <MenuFilterDwhConfig
                    table={state.table}
                    group={state.group}
                    dataWarehousePopoverFields={dataWarehousePopoverFields}
                    insightProps={insightProps}
                    onCommit={handleCommit}
                    // Restore the origin surface — menu (when the dialog
                    // was opened straight from the trigger because a DWH
                    // selection already existed) or the table picker
                    // (when the user drilled down through dwh-pick).
                    onBack={state.origin === 'menu' ? openMenu : openDwhPick}
                />
            )}
            <DropdownMenuContent align="start" className="min-w-[240px]">
                <DropdownMenuItem onClick={() => openCombobox('all')} data-attr="taxonomic-filter-menu-new">
                    New filter…
                    <ChevronRight className="ml-auto size-3.5 text-tertiary" />
                </DropdownMenuItem>
                {recentEntries.length > 0 && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => openCombobox('recent')}>
                            Recent
                            <ChevronRight className="ml-auto size-3.5 text-tertiary" />
                        </DropdownMenuItem>
                    </>
                )}
                {pinnedEntries.length > 0 && (
                    <DropdownMenuItem onClick={() => openCombobox('pinned')}>
                        Pinned
                        <ChevronRight className="ml-auto size-3.5 text-tertiary" />
                    </DropdownMenuItem>
                )}
                {(hasDwh || hasHogql) && <DropdownMenuSeparator />}
                {hasDwh && (
                    <DropdownMenuItem onClick={openDwhPick} data-attr="taxonomic-filter-menu-dwh">
                        Data warehouse tables
                        <ChevronRight className="ml-auto size-3.5 text-tertiary" />
                    </DropdownMenuItem>
                )}
                {hasHogql && (
                    <DropdownMenuItem onClick={openHogql} data-attr="taxonomic-filter-menu-hogql">
                        HogQL expression
                        <ChevronRight className="ml-auto size-3.5 text-tertiary" />
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

interface ShortcutItem {
    name?: string
    id?: unknown
    value?: unknown
    // `_pinnedContext.value` and `_recentContext.sourceValue` mean the
    // same thing — the source-group field name diverged in master while
    // this branch was in flight; consumers (this menu) read whichever
    // shape exists. See `taxonomicFilterPinnedPropertiesLogic` /
    // `recentTaxonomicFiltersLogic`.
    _pinnedContext?: { sourceGroupType?: TaxonomicFilterGroupType; value?: unknown }
    _recentContext?: { sourceGroupType?: TaxonomicFilterGroupType; sourceValue?: unknown }
}

/**
 * Resolve the most appropriate `TaxonomicFilterGroup` for a shortcut
 * item.
 *
 *   1. Recorded `sourceGroupType` if it points at a real content group
 *      that's available right now.
 *   2. If the recorded source is a META group (Suggested / Recent /
 *      Pinned), find a non-meta group in `groups` whose `getValue(item)`
 *      matches the saved value — that's the underlying definition the
 *      item really belongs to (e.g. SuggestedFilters → Events).
 *   3. Fall back to the first non-meta group so the row at least has a
 *      sensible category subtitle instead of "Suggested filters".
 */
function resolveShortcutGroup(
    item: ShortcutItem,
    sourceType: TaxonomicFilterGroupType | undefined,
    sourceValue: unknown,
    groups: TaxonomicFilterGroup[]
): TaxonomicFilterGroup | null {
    if (sourceType && !META_GROUP_TYPES.has(sourceType)) {
        const direct = groups.find((g) => g.type === sourceType)
        if (direct) {
            return direct
        }
    }
    const matchByValue = groups.find((g) => {
        if (META_GROUP_TYPES.has(g.type)) {
            return false
        }
        try {
            const candidate = g.getValue?.(item as TaxonomicDefinitionTypes)
            return candidate != null && candidate === sourceValue
        } catch {
            return false
        }
    })
    if (matchByValue) {
        return matchByValue
    }
    return groups.find((g) => !META_GROUP_TYPES.has(g.type)) ?? null
}

function mapShortcutItems(items: ShortcutItem[], groups: TaxonomicFilterGroup[]): MenuFilterEntry[] {
    return items
        .map((item) => {
            const ctx = item._recentContext ?? item._pinnedContext
            const sourceType = ctx?.sourceGroupType
            // Recent stores the value under `sourceValue`, pinned under
            // `value`. Read whichever side exists.
            const sourceValue =
                (ctx as { sourceValue?: unknown } | undefined)?.sourceValue ??
                (ctx as { value?: unknown } | undefined)?.value
            const group = resolveShortcutGroup(item, sourceType, sourceValue, groups)
            if (!group) {
                return null
            }
            const name = (item.name as string) ?? group.getName?.(item as TaxonomicDefinitionTypes) ?? ''
            return {
                item: item as TaxonomicDefinitionTypes,
                group,
                name,
                friendlyLabel: getCoreFilterDefinition(name, group.type)?.label,
            } as MenuFilterEntry
        })
        .filter((e): e is MenuFilterEntry => e != null)
}
