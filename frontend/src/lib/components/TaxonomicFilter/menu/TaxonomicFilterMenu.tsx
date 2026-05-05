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
import { TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from '../types'
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
}: TaxonomicFilterMenuProps): JSX.Element {
    const { groups, selectItem, inputProps } = useTaxonomicFilterContext()
    const [state, setState] = useState<MenuFilterState>({ kind: 'closed' })

    // -- Transitions -- single source of truth for state changes. Each
    // transition is a single setState call so React batches and there's
    // no intermediate flicker.
    const closeAll = useCallback(() => setState({ kind: 'closed' }), [])
    const openMenu = useCallback(() => setState({ kind: 'menu' }), [])
    const openCombobox = useCallback((drillTo: DrillCategory) => setState({ kind: 'combobox', drillTo }), [])
    const openDwhPick = useCallback(() => setState({ kind: 'dwh-pick' }), [])
    const openDwhConfig = useCallback(
        (table: TaxonomicDefinitionTypes, group: TaxonomicFilterGroup) =>
            setState({ kind: 'dwh-config', table, group }),
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
            return { kind: 'dwh-config', table: selected.item, group: selected.group }
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
            selectItem(entry.group, itemValue, mergedItem)
            onCommit?.({ ...entry, item: mergedItem }, extra)
            closeAll()
        },
        [selectItem, onCommit, closeAll]
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
    const popoverOpen =
        state.kind === 'combobox' ||
        state.kind === 'dwh-pick' ||
        state.kind === 'dwh-config' ||
        state.kind === 'hogql-edit'

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
            if (target.closest?.('[data-slot="popover-content"]')) {
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
                <span ref={triggerWrapRef} className="relative inline-flex">
                    <DropdownMenuTrigger render={triggerEl} data-attr="taxonomic-filter-menu-trigger" />
                    <PopoverTrigger
                        render={<span aria-hidden tabIndex={-1} className="absolute inset-0 pointer-events-none" />}
                    />
                </span>
                <PopoverContent
                    align="start"
                    side="bottom"
                    sideOffset={4}
                    className={cn('p-0 gap-0 overflow-hidden flex flex-col w-[720px] h-[400px]')}
                >
                    {state.kind === 'combobox' && (
                        <MenuFilterCombobox
                            drillTo={state.drillTo}
                            drillItems={
                                state.drillTo === 'recent'
                                    ? recentEntries
                                    : state.drillTo === 'pinned'
                                      ? pinnedEntries
                                      : undefined
                            }
                            placeholder={placeholder ?? inputProps.placeholder}
                            selectedEntry={selected ?? null}
                            onCommit={handleCommit}
                            onBack={openMenu}
                        />
                    )}
                    {state.kind === 'dwh-pick' && (
                        <MenuFilterCombobox
                            drillTo={TaxonomicFilterGroupType.DataWarehouse}
                            title="Data warehouse tables"
                            placeholder="Search tables…"
                            selectedEntry={
                                selected?.group.type === TaxonomicFilterGroupType.DataWarehouse ? selected : null
                            }
                            onCommit={(entry) => openDwhConfig(entry.item, entry.group)}
                            onBack={openMenu}
                        />
                    )}
                    {state.kind === 'dwh-config' && (
                        <MenuFilterDwhConfig
                            table={state.table}
                            group={state.group}
                            onCommit={handleCommit}
                            onBack={openDwhPick}
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
    value?: unknown
    _pinnedContext?: { sourceGroupType?: TaxonomicFilterGroupType }
}

function mapShortcutItems(items: ShortcutItem[], groups: TaxonomicFilterGroup[]): MenuFilterEntry[] {
    return items
        .map((item) => {
            const sourceType = item._pinnedContext?.sourceGroupType
            const group = sourceType ? groups.find((g) => g.type === sourceType) : groups[0]
            if (!group) {
                return null
            }
            const name = group.getName?.(item as TaxonomicDefinitionTypes) ?? item.name ?? ''
            return {
                item: item as TaxonomicDefinitionTypes,
                group,
                name,
                friendlyLabel: getCoreFilterDefinition(name, group.type)?.label,
            } as MenuFilterEntry
        })
        .filter((e): e is MenuFilterEntry => e != null)
}
