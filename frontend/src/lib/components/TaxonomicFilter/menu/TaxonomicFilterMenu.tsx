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
import posthog from 'posthog-js'
import { ReactElement, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconChevronRight, IconFilter } from '@posthog/icons'
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

import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { isDefinitionStale } from 'lib/utils/definitions'

import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { AnyPropertyFilter, EventDefinition } from '~/types'

import { useTaxonomicFilterContext } from '../headless/context'
import { recentTaxonomicFiltersLogic } from '../recentTaxonomicFiltersLogic'
import { taxonomicFilterPinnedPropertiesLogic } from '../taxonomicFilterPinnedPropertiesLogic'
import { isQuickFilterItem, META_GROUP_TYPES, TaxonomicDefinitionTypes, TaxonomicFilterGroupType } from '../types'
import { filterPinnedForContext, filterRecentsForContext } from '../utils/suggestedContextFilters'
import { MenuFilterCombobox } from './Combobox'
import { MenuFilterDwhConfig } from './DwhFlow'
import { MenuFilterHogQLEditor } from './HogQLEditor'
import { MenuInputTrigger } from './InputTrigger'
import { taxonomicTriggerWrapperClassName } from './triggerLayout'
import {
    CommitFn,
    DrillCategory,
    MenuFilterEntry,
    MenuFilterState,
    TAXONOMIC_FILTER_SURFACE,
    TaxonomicFilterGroup,
} from './types'

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
    /**
     * Stretch the trigger to its parent's full width. When false (default)
     * the trigger sizes to its content and caps at the parent — matching a
     * plain inline button so it truncates instead of overflowing a shared
     * flex row. Set true for dedicated full-width trigger columns.
     */
    fullWidthTrigger?: boolean
    /**
     * Open the menu immediately on mount. Used by consumers that lazily
     * mount this component on the user's first trigger click — without it
     * the click that mounts the component wouldn't also open it.
     */
    defaultOpen?: boolean
    /**
     * Extra node rendered inside the trigger wrapper (which is `relative`),
     * e.g. an absolutely-positioned corner badge. Kept inside the wrapper so
     * callers don't need to add another positioned ancestor of their own.
     */
    triggerAccessory?: import('react').ReactNode
    /**
     * Trigger presentation. `'button'` (default) is the single dropdown
     * button. `'input'` renders a replay-style search box with a leading
     * filter-icon button: focusing/typing in the box opens the combobox,
     * clicking the icon opens the dropdown menu. Only takes effect while
     * nothing is `selected` (the add-filter case) — an existing selection
     * still renders the button so its label is visible.
     */
    triggerVariant?: 'button' | 'input'
    /**
     * Where `defaultOpen` lands. Defaults to `resolveOpenState()` (menu when
     * nothing is selected). The input trigger uses this so an open driven by
     * the search box arrives directly on the combobox while one driven by the
     * filter icon arrives on the dropdown menu.
     */
    defaultOpenState?: 'menu' | 'combobox'
}

export interface TriggerState {
    label: string
    selected: MenuFilterEntry | null
    open: boolean
}

/** Dropdown-menu options users can pick, for the option-click event. */
type MenuOption = 'new' | 'recent' | 'pinned' | 'dwh' | 'hogql'

// Module-level so a quick close→reopen is detectable even though the
// component unmounts between opens (consumers lazily mount it on the
// first trigger click). Heuristic only — shared across all triggers.
let lastMenuClosedAtMs: number | null = null
const QUICK_REOPEN_MS = 3000

// The input-trigger panel is shifted up + left so its search field lands over
// the trigger row (the input appears to stay put and only widen). The shift
// equals the field's offset from the panel's top-left, summed from the pieces
// that produce it — kept as named parts so a change to `MenuFilterHeader`'s
// spacing or the input row's padding is visibly the thing to keep in sync here.
const MENU_HEADER_PADDING_Y_PX = 16 // MenuFilterHeader `py-2` (top + bottom)
const MENU_HEADER_BUTTON_HEIGHT_PX = 24 // "Go back" Button `size="sm"` (h-6)
const MENU_HEADER_BORDER_PX = 1 // MenuFilterHeader `border-b`
const SEARCH_ROW_PADDING_PX = 8 // search-field row `p-2` (one side)
const PANEL_BORDER_PX = 1 // PopoverContent border

/** Panel-top to search-field-top: the header (padding + button + border) plus the
 *  search row's top padding. */
const INPUT_TRIGGER_PANEL_HEADER_OFFSET =
    MENU_HEADER_PADDING_Y_PX + MENU_HEADER_BUTTON_HEIGHT_PX + MENU_HEADER_BORDER_PX + SEARCH_ROW_PADDING_PX

/** Panel-left to search-field-left: the panel border plus the search row's left
 *  padding. */
const INPUT_TRIGGER_PANEL_LEFT_INSET = PANEL_BORDER_PX + SEARCH_ROW_PADDING_PX

/** Mirrors legacy `taxonomicFilterLogic`: staleness only applies to event /
 *  custom-event definitions that carry `last_seen_at`; `undefined` for every
 *  other selection so the field reads identically across the A/B arms. */
export function eventSelectionWasStale(
    sourceGroupType: TaxonomicFilterGroupType,
    item: TaxonomicDefinitionTypes
): boolean | undefined {
    const isEventSelection =
        sourceGroupType === TaxonomicFilterGroupType.Events || sourceGroupType === TaxonomicFilterGroupType.CustomEvents
    if (!isEventSelection || !item || typeof item !== 'object' || !('last_seen_at' in item)) {
        return undefined
    }
    return isDefinitionStale(item as unknown as EventDefinition)
}

/** The default combobox landing — the "All" scope, where recents/pinned lead and
 *  the user can search across every category. The one home for this state so the
 *  initial-mount and runtime open paths can't drift. */
const comboboxAllState = (): MenuFilterState => ({ kind: 'combobox', drillTo: 'all' })

/**
 * Resolve the panel a trigger open should land on from the current selection.
 * If `selected` is set, jump straight into the panel that matches its group so
 * the user lands on something editable (e.g. the HogQL editor pre-filled with
 * the existing expression) instead of having to re-traverse the dropdown menu.
 * With no selection we fall back to the menu.
 */
export function resolveSelectedOpenState(selected: MenuFilterEntry | null): MenuFilterState {
    if (!selected) {
        return { kind: 'menu' }
    }
    if (selected.group.type === TaxonomicFilterGroupType.HogQLExpression) {
        return { kind: 'hogql-edit' }
    }
    if (selected.group.type === TaxonomicFilterGroupType.DataWarehouse) {
        // origin='menu' so X / Esc / Cancel return to the dropdown menu rather
        // than dropping the user into the (unscrolled) dwh-pick list they never
        // visited.
        return { kind: 'dwh-config', table: selected.item, group: selected.group, origin: 'menu' }
    }
    // The committed selection floats to the first row (and stays highlighted) so
    // the user can verify it at a glance.
    return comboboxAllState()
}

/**
 * Initial menu state at mount. `defaultOpen` consumers lazily mount this
 * component on the user's first trigger interaction, so opening is a one-shot
 * mount concern — it belongs in the initial state, not a post-paint effect, so
 * the picker opens in the same commit it mounts (no intermediate closed frame).
 * `defaultOpenState` routes the open to the panel matching the interaction (the
 * input trigger's search box -> combobox, its filter icon -> menu).
 */
export function resolveInitialMenuState(
    defaultOpen: boolean,
    defaultOpenState: 'menu' | 'combobox' | undefined,
    selected: MenuFilterEntry | null
): MenuFilterState {
    if (!defaultOpen) {
        return { kind: 'closed' }
    }
    if (defaultOpenState === 'combobox') {
        return comboboxAllState()
    }
    if (defaultOpenState === 'menu') {
        return { kind: 'menu' }
    }
    return resolveSelectedOpenState(selected)
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
    fullWidthTrigger = false,
    defaultOpen = false,
    triggerAccessory,
    triggerVariant = 'button',
    defaultOpenState,
}: TaxonomicFilterMenuProps): JSX.Element {
    const { groups, selectItem, inputProps, searchQuery, setSearchQuery, selectingKeyOnly, excludedOperators } =
        useTaxonomicFilterContext()
    const [state, setState] = useState<MenuFilterState>(() =>
        resolveInitialMenuState(defaultOpen, defaultOpenState, selected ?? null)
    )

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
            const now = Date.now()
            const msSinceLastClose = lastMenuClosedAtMs != null ? now - lastMenuClosedAtMs : null
            openedAtRef.current = now
            hadCommitRef.current = false
            posthog.capture('taxonomic filter menu opened', {
                openedTo: next,
                hadSelection: !!selected,
                triggerLabel,
                // Reopen funnel — `null` on the first open of the session;
                // a small value means the user bounced and came right back.
                msSinceLastClose,
                reopenedQuickly: msSinceLastClose != null && msSinceLastClose < QUICK_REOPEN_MS,
            })
        } else if (previous !== 'closed' && next !== 'closed' && previous !== next) {
            posthog.capture('taxonomic filter menu drilled', {
                fromState: previous,
                toState: next,
            })
        } else if (previous !== 'closed' && next === 'closed') {
            const closedAt = Date.now()
            const dwellMs = openedAtRef.current ? closedAt - openedAtRef.current : null
            posthog.capture('taxonomic filter menu closed', {
                dwellMs,
                hadCommit: hadCommitRef.current,
                lastState: previous,
            })
            // Legacy `taxonomic filter *` contract — emitted alongside the
            // menu-specific events so the rebuild is comparable to the
            // control/pill variants by feature-flag value.
            // Legacy's `groupType: activeTab` is omitted because the menu has no single active tab at close time.
            posthog.capture('taxonomic filter closed', {
                surface: TAXONOMIC_FILTER_SURFACE,
                dwellMs,
                hadSelection: hadCommitRef.current,
            })
            lastMenuClosedAtMs = closedAt
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

    // Capture which dropdown-menu option the user picked, then run its
    // transition. Lets us see the relative pull of New / Recent / Pinned /
    // DWH / HogQL rather than just a generic menu→panel `drilled` event.
    const selectMenuOption = useCallback((option: MenuOption, action: () => void): void => {
        posthog.capture('taxonomic filter menu option clicked', { option })
        action()
    }, [])

    const resolveOpenState = useCallback((): MenuFilterState => resolveSelectedOpenState(selected ?? null), [selected])

    // -- Recent / Pinned shortcuts -- read from kea so menu items reflect
    // the live counts. Mapped back to entries via source group.
    const { recentFilterItems } = useValues(recentTaxonomicFiltersLogic)
    const { pinnedFilterItems } = useValues(taxonomicFilterPinnedPropertiesLogic)

    // Only recents/pinned whose source group is one of this picker's groups —
    // a global recent from a different picker (e.g. a cohort in an events-only
    // picker) would otherwise be remapped onto a fallback group and shown under
    // the wrong category.
    const taxonomicGroupTypes = useMemo(() => groups.map((g) => g.type), [groups])
    const recentEntries = useMemo<MenuFilterEntry[]>(
        () =>
            mapShortcutItems(
                filterRecentsForContext(
                    recentFilterItems as TaxonomicDefinitionTypes[],
                    taxonomicGroupTypes,
                    excludedOperators,
                    selectingKeyOnly
                ) as ShortcutItem[],
                groups
            ),
        [recentFilterItems, taxonomicGroupTypes, groups, excludedOperators, selectingKeyOnly]
    )
    const pinnedEntries = useMemo<MenuFilterEntry[]>(
        () =>
            mapShortcutItems(
                filterPinnedForContext(
                    pinnedFilterItems as TaxonomicDefinitionTypes[],
                    taxonomicGroupTypes
                ) as ShortcutItem[],
                groups
            ),
        [pinnedFilterItems, taxonomicGroupTypes, groups]
    )

    const hasDwh = groups.some((g) => g.type === TaxonomicFilterGroupType.DataWarehouse)
    const hasHogql = groups.some((g) => g.type === TaxonomicFilterGroupType.HogQLExpression)

    // -- Commit -- routes through orchestrator's `selectItem` AND the
    // consumer's `onCommit` callback. Closes everything.
    const handleCommit = useCallback<CommitFn>(
        (entry, extra, selection) => {
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
                // Time-to-select — how long from opening the menu to
                // committing this item.
                msSinceOpen: openedAtRef.current ? Date.now() - openedAtRef.current : null,
            })
            // Legacy contract, fired from this final-commit funnel rather than on
            // row click so it counts only committed selections — a DWH table pick
            // that opens (and is then cancelled from) the config form never reaches
            // here, while a config-form or HogQL commit does. `groupType` is the
            // active scope (mirrors legacy `activeTab`); `sourceGroupType` is the
            // row's origin group — they differ for a recent/pinned row on the All
            // surface. `selection` is absent for non-row commits (DWH form, HogQL).
            // `wasStale` mirrors legacy for event/custom-event selections; `wasQuickFilter`
            // uses the same predicate as legacy, though the menu surfaces no quick-filter
            // items so it is false in practice and the legacy quick-filter field spread
            // never applies here.
            // `position` is the rendered row index (same coordinate as legacy's
            // `meta.position`): directly comparable on single-group scopes, and
            // surface-relative on the merged "All" scope, which leads with the
            // recents/pinned prefix and has no single-tab legacy equivalent.
            posthog.capture('taxonomic filter item selected', {
                surface: TAXONOMIC_FILTER_SURFACE,
                groupType: selection?.groupType,
                sourceGroupType: entry.group.type,
                wasFromRecents: selection?.wasFromRecents ?? false,
                wasFromPinnedList: selection?.wasFromPinnedList ?? false,
                wasQuickFilter: isQuickFilterItem(entry.item),
                hadSearchInput: !!searchQuery,
                position: selection?.position,
                query: searchQuery || undefined,
                wasStale: eventSelectionWasStale(entry.group.type, entry.item),
                // True when the row is the synthetic "URL contains <query>" shortcut
                // rather than a real picked item — lets us measure its adoption.
                wasUrlContainsShortcut: (entry.item as { isContainsShortcut?: boolean }).isContainsShortcut === true,
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

    // Replay-style input trigger — only while nothing is selected, so an
    // existing selection keeps showing its label in the button. The icon is
    // the dropdown-menu anchor; the input opens (and seeds) the combobox.
    const useInputTrigger = triggerVariant === 'input' && !selected
    const inputTriggerPlaceholder = triggerLabel || inputProps.placeholder || 'Add filter'

    // When the input-trigger combobox is open, the popover panel renders the
    // live search field (header above it, results below) and is shifted up so
    // that field lands over the trigger row — the chrome wraps the input. The
    // shared ref lets the popover focus that field on open.
    const comboboxInputRef = useRef<HTMLInputElement | null>(null)

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

    // `combobox` and `dwh-pick` render a search-field row, so in input-trigger
    // mode the panel is shifted to overlay that field on the trigger box (and the
    // trigger yields to an invisible spacer). `hogql-edit` is intentionally
    // excluded: the code editor has no search-field row to align to, so it opens
    // as a normal dropdown below the trigger.
    const comboboxOverlaysTrigger = useInputTrigger && (state.kind === 'combobox' || state.kind === 'dwh-pick')

    // Filter-icon menu anchor, styled to match the scene (LemonButton). Lives
    // as the field's prefix — in the resting trigger box, and in the combobox's
    // portaled field while open — so it stays put as the menu opens around it.
    const inputTriggerIcon = (
        <DropdownMenuTrigger
            render={
                <LemonButton
                    size="small"
                    icon={<IconFilter />}
                    aria-label="Open filter menu"
                    data-attr="taxonomic-filter-menu-trigger"
                    // Stop the click bubbling to the LemonInput wrapper, whose
                    // onClick focuses the input — that would open the combobox
                    // instead of the icon's dropdown menu.
                    onClick={(e) => e.stopPropagation()}
                />
            }
        />
    )

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
            // Monaco portals suggestion widgets to a shared body-level div; treat clicks there as
            // inside so picking a SQL autocomplete value doesn't close the filter.
            if (target.closest?.('[data-attr="monaco-overflow-root"]')) {
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
                    if (eventDetails.reason === 'escape-key') {
                        closeAll()
                        return
                    }
                    eventDetails.cancel()
                }}
            >
                <span ref={triggerWrapRef} data-lemon-skin className={taxonomicTriggerWrapperClassName(fullWidthTrigger)}>
                    {useInputTrigger ? (
                        <MenuInputTrigger
                            iconButton={inputTriggerIcon}
                            fullWidth={fullWidthTrigger}
                            placeholder={inputTriggerPlaceholder}
                            value={searchQuery}
                            spacerOnly={comboboxOverlaysTrigger}
                            onChange={(next) => {
                                setSearchQuery(next)
                                if (state.kind !== 'combobox') {
                                    openCombobox('all')
                                }
                            }}
                            onFocus={() => {
                                if (state.kind === 'closed') {
                                    openCombobox('all')
                                }
                            }}
                        />
                    ) : (
                        <DropdownMenuTrigger render={triggerEl} data-attr="taxonomic-filter-menu-trigger" />
                    )}
                    <PopoverTrigger
                        nativeButton={false}
                        render={<span aria-hidden tabIndex={-1} className="absolute inset-0 pointer-events-none" />}
                    />
                    {triggerAccessory}
                </span>
                <PopoverContent
                    // Lemon-skin the panel (lemon-skin.scss) — the attribute must
                    // ride on the portaled element itself, wrappers can't reach it
                    data-lemon-skin
                    align="start"
                    side="bottom"
                    // Input trigger: shift the panel up by (trigger height +
                    // header + input-row padding) so the panel's search field
                    // lands over the trigger row — header pops above, results
                    // below, the input appears to stay put and just widen. Keep
                    // the side fixed so it can't flip away from that alignment.
                    // Button trigger: a normal dropdown below the button.
                    sideOffset={
                        comboboxOverlaysTrigger
                            ? ({ anchor }) => -(anchor.height + INPUT_TRIGGER_PANEL_HEADER_OFFSET)
                            : 4
                    }
                    // Pull the panel left so its inset search field aligns with
                    // the trigger box horizontally (input appears not to move).
                    alignOffset={comboboxOverlaysTrigger ? -INPUT_TRIGGER_PANEL_LEFT_INSET : 0}
                    // Input trigger: pin the vertical axis so the field stays over
                    // the trigger row, but allow horizontal `shift` so the wide
                    // panel slides left to stay on-screen when the trigger sits near
                    // the right edge (e.g. web-analytics filters) — losing a few px
                    // of horizontal alignment there beats clipping off-screen.
                    // Button trigger: keep it on the vertical axis, never beside.
                    collisionAvoidance={
                        comboboxOverlaysTrigger
                            ? { side: 'none', align: 'shift' }
                            : { side: 'flip', align: 'shift', fallbackAxisSide: 'none' }
                    }
                    container={popoverContainer ?? undefined}
                    // Focus the panel's search field on open (it's outside the
                    // popover's default focusable flow until rendered).
                    initialFocus={comboboxOverlaysTrigger ? comboboxInputRef : undefined}
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
                                      : undefined
                            }
                            // Recents/pinned lead the default "All" surface
                            // (fixed order: recents, then pinned).
                            recentEntries={recentEntries}
                            pinnedEntries={pinnedEntries}
                            placeholder={placeholder ?? inputProps.placeholder}
                            // Only override the default "Choose filter"
                            // header when on the All chip — drilled views
                            // already title themselves with the group name.
                            title={state.drillTo === 'all' ? comboboxTitle : undefined}
                            selectedEntry={selected ?? null}
                            onCommit={handleCommit}
                            onBack={openMenu}
                            inputRef={comboboxInputRef}
                            iconButton={useInputTrigger ? inputTriggerIcon : undefined}
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
                            inputRef={comboboxInputRef}
                            iconButton={useInputTrigger ? inputTriggerIcon : undefined}
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
            <DropdownMenuContent data-lemon-skin align="start" className="min-w-[240px]">
                {/* The input-trigger box already does "type to make a new filter",
                    so the explicit "New filter…" row would be redundant there. */}
                {!useInputTrigger && (
                    <DropdownMenuItem
                        onClick={() => selectMenuOption('new', () => openCombobox('all'))}
                        data-attr="taxonomic-filter-menu-new"
                    >
                        New filter…
                        <IconChevronRight className="ml-auto size-3.5 text-tertiary" />
                    </DropdownMenuItem>
                )}
                {recentEntries.length > 0 && (
                    <>
                        {!useInputTrigger && <DropdownMenuSeparator />}
                        <DropdownMenuItem onClick={() => selectMenuOption('recent', () => openCombobox('recent'))}>
                            Recent
                            <IconChevronRight className="ml-auto size-3.5 text-tertiary" />
                        </DropdownMenuItem>
                    </>
                )}
                {pinnedEntries.length > 0 && (
                    <DropdownMenuItem onClick={() => selectMenuOption('pinned', () => openCombobox('pinned'))}>
                        Pinned
                        <IconChevronRight className="ml-auto size-3.5 text-tertiary" />
                    </DropdownMenuItem>
                )}
                {(hasDwh || hasHogql) && <DropdownMenuSeparator />}
                {hasDwh && (
                    <DropdownMenuItem
                        onClick={() => selectMenuOption('dwh', openDwhPick)}
                        data-attr="taxonomic-filter-menu-dwh"
                    >
                        Data warehouse tables
                        <IconChevronRight className="ml-auto size-3.5 text-tertiary" />
                    </DropdownMenuItem>
                )}
                {hasHogql && (
                    <DropdownMenuItem
                        onClick={() => selectMenuOption('hogql', openHogql)}
                        data-attr="taxonomic-filter-menu-hogql"
                    >
                        HogQL expression
                        <IconChevronRight className="ml-auto size-3.5 text-tertiary" />
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
    _recentContext?: {
        sourceGroupType?: TaxonomicFilterGroupType
        sourceValue?: unknown
        propertyFilter?: AnyPropertyFilter
    }
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
            const recentPropertyFilter = item._recentContext?.propertyFilter
            return {
                item: item as TaxonomicDefinitionTypes,
                group,
                name,
                friendlyLabel: getCoreFilterDefinition(name, group.type)?.label,
                ...(recentPropertyFilter
                    ? { recentPropertyFilter, recentLabel: formatPropertyLabel(recentPropertyFilter, {}) }
                    : {}),
            } as MenuFilterEntry
        })
        .filter((e): e is MenuFilterEntry => e != null)
}
