/**
 * Dropdown-menu-fronted taxonomic filter.
 *
 * See `../headless/UX_SPEC.md` for the design.
 *
 * Architecture:
 *   - One state machine at the top (`MenuFilterState`).
 *   - Trigger button is the *single* anchor for both the dropdown menu
 *     and the popover. The menu uses base-ui's own trigger registration;
 *     the popover anchors to the trigger ref via `Positioner.anchor`.
 *   - Each panel (Combobox / DwhTables / DwhConfig / HogQL) is a pure
 *     component; it receives data + callbacks. No registration hooks.
 *
 * Consumer wraps it in `<TaxonomicFilterHeadless.Root>` so we can read
 * `groups` + `selectItem` via context (same orchestrator the legacy /
 * old headless components use).
 */
import { useValues } from 'kea'
import { ReactElement, useCallback, useMemo, useState } from 'react'

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
    // component (DropdownMenu); the popover is open for any non-menu,
    // non-closed kind.
    const popoverOpen =
        state.kind === 'combobox' ||
        state.kind === 'dwh-pick' ||
        state.kind === 'dwh-config' ||
        state.kind === 'hogql-edit'

    return (
        <DropdownMenu
            open={state.kind === 'menu'}
            onOpenChange={(open) => {
                if (open) {
                    openMenu()
                    return
                }
                // Functional setState — when a menu item's onClick already
                // advanced state (e.g. to 'combobox'), the subsequent menu
                // auto-close shouldn't yank us back to 'closed'. Use the
                // latest staged state, not the value from the render closure.
                setState((current) => (current.kind === 'menu' ? { kind: 'closed' } : current))
            }}
        >
            {/* Wrapper around the trigger button: a hidden `PopoverTrigger`
                span overlays it (`absolute inset-0 pointer-events-none`)
                purely as the popover's anchor. The visible button only
                handles menu-trigger clicks; the overlay receives no
                events but Floating UI uses its bounding rect. Clean
                composition without compose-render-on-same-button. */}
            <Popover open={popoverOpen} onOpenChange={(open) => !open && closeAll()}>
                <span className="relative inline-flex">
                    <DropdownMenuTrigger render={triggerEl} data-attr="taxonomic-filter-menu-trigger" />
                    <PopoverTrigger
                        render={<span aria-hidden tabIndex={-1} className="absolute inset-0 pointer-events-none" />}
                    />
                </span>
                <PopoverContent
                    align="start"
                    side="bottom"
                    sideOffset={4}
                    className={cn('p-0 gap-0 w-(--anchor-width) min-w-[320px] h-[480px] overflow-hidden flex flex-col')}
                >
                    {/* Render the active panel. `back` returns to the
                        dropdown menu (per spec). */}
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
                            onCommit={handleCommit}
                            onBack={openMenu}
                        />
                    )}
                    {state.kind === 'dwh-pick' && (
                        // Reuse the combobox in single-group drill mode —
                        // searchable, scrollable, no chips. `onCommit`
                        // routes into the config form instead of
                        // committing directly (DWH tables need column
                        // setup before they're a valid selection).
                        <MenuFilterCombobox
                            drillTo={TaxonomicFilterGroupType.DataWarehouse}
                            title="Data warehouse tables"
                            placeholder="Search tables…"
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
                    {state.kind === 'hogql-edit' && <MenuFilterHogQLEditor onCommit={handleCommit} onBack={openMenu} />}
                </PopoverContent>
            </Popover>
            <DropdownMenuContent align="start" className="min-w-[240px]">
                <DropdownMenuItem onClick={() => openCombobox('all')} data-attr="taxonomic-filter-menu-new">
                    New filter…
                </DropdownMenuItem>
                {recentEntries.length > 0 && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem onClick={() => openCombobox('recent')}>Recent</DropdownMenuItem>
                    </>
                )}
                {pinnedEntries.length > 0 && (
                    <DropdownMenuItem onClick={() => openCombobox('pinned')}>Pinned</DropdownMenuItem>
                )}
                {(hasDwh || hasHogql) && <DropdownMenuSeparator />}
                {hasDwh && (
                    <DropdownMenuItem onClick={openDwhPick} data-attr="taxonomic-filter-menu-dwh">
                        Data warehouse tables
                    </DropdownMenuItem>
                )}
                {hasHogql && (
                    <DropdownMenuItem onClick={openHogql} data-attr="taxonomic-filter-menu-hogql">
                        HogQL expression
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
