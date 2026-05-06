/**
 * Top-level orchestrator hook for the headless TaxonomicFilter.
 *
 * Owns:
 *   - search query (controlled or uncontrolled)
 *   - active group type (controlled or uncontrolled)
 *   - resolved + ordered taxonomicGroups[] (filtered against the consumer's
 *     `taxonomicGroupTypes` prop, with shortcut group promotion + meta tab
 *     auto-injection)
 *   - active-list registration for keyboard nav (each tab list component
 *     registers its useGroupList api; the orchestrator forwards key events
 *     to the currently active one)
 *   - selectItem callback fan-out (dispatches to props.onChange)
 *
 * Does NOT own:
 *   - per-tab list state (that's `useGroupList`, called inside each tab
 *     component)
 *   - top-match aggregation across groups (deferred to a follow-up; today's
 *     kea `appendTopMatches` reducer can stay until each tab has migrated)
 *   - recents / pinned localStorage logic (still in `recentTaxonomicFiltersLogic`
 *     and `taxonomicFilterPinnedPropertiesLogic`; the orchestrator only reads
 *     them via the bridge, doesn't write)
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
    hasRecentContext,
    recentTaxonomicFiltersLogic,
    stripRecentContext,
} from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import {
    AllowedProperties,
    ExcludedProperties,
    SelectedProperties,
    SimpleOption,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
    META_GROUP_TYPES,
} from 'lib/components/TaxonomicFilter/types'
import { isQuickFilterItem } from 'lib/components/TaxonomicFilter/types'
import { buildTaxonomicGroups } from 'lib/components/TaxonomicFilter/utils/buildTaxonomicGroups'
import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'
import { teamLogic } from 'scenes/teamLogic'

import { AnyDataNode } from '~/queries/schema/schema-general'

import { UseGroupListInput, UseGroupListResult } from './useGroupList'
import { useTaxonomicGroupsContext } from './useTaxonomicGroupsContext'
import { useTaxonomicLocalOverrides } from './useTaxonomicLocalOverrides'

export interface UseTaxonomicFilterOptions {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]

    // controlled value
    value?: TaxonomicFilterValue
    onChange?: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue, item: any) => void
    onEnter?: (query: string) => void

    // initial / controlled tab
    groupType?: TaxonomicFilterGroupType

    // search input
    searchQuery?: string
    initialSearchQuery?: string
    onSearchQueryChange?: (q: string) => void

    // forwarded into useTaxonomicGroupsContext (only fields that affect group config)
    eventNames?: string[]
    schemaColumns?: import('~/queries/schema/schema-general').DatabaseSchemaField[]
    schemaColumnsLoading?: boolean
    metadataSource?: AnyDataNode
    suggestedFiltersLabel?: string
    excludedProperties?: ExcludedProperties
    selectedProperties?: SelectedProperties
    propertyAllowList?: AllowedProperties
    maxContextOptions?: MaxContextTaxonomicFilterOption[]
    hideBehavioralCohorts?: boolean
    endpointFilters?: Record<string, any>
    hogQLGlobals?: Record<string, any>
    hogQLExpressionShowBreakdownLabelHint?: boolean

    // forwarded into per-tab useGroupList
    optionsFromProp?: Partial<Record<TaxonomicFilterGroupType, SimpleOption[]>>
    showNumericalPropsOnly?: boolean
    minSearchQueryLength?: number
    allowNonCapturedEvents?: boolean
    enableKeywordShortcuts?: boolean
    selectFirstItem?: boolean
    autoSelectItem?: boolean
}

export interface TaxonomicFilterApi {
    // group resolution
    /** Ordered list of group configs that should appear as tabs. */
    groups: TaxonomicFilterGroup[]
    /** Just the group types from `groups`, in display order. */
    groupTypes: TaxonomicFilterGroupType[]
    /** Identity of the meta groups in `groups` (read by per-tab UIs to suppress loaders, top matches etc.). */
    metaGroupTypes: Set<TaxonomicFilterGroupType>
    activeGroup: TaxonomicFilterGroup | undefined
    activeGroupType: TaxonomicFilterGroupType
    setActiveGroupType: (groupType: TaxonomicFilterGroupType) => void
    tabLeft: () => void
    tabRight: () => void

    // search
    searchQuery: string
    setSearchQuery: (q: string) => void
    /** Composite placeholder string (e.g. "events, properties or other..."). */
    searchPlaceholder: string

    // selection
    selectItem: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue | null, item: any) => void
    /** Forwards Enter to the registered active list, falling back to onEnter(query). */
    selectSelected: () => void

    // active-list registration (called by the per-tab list component)
    registerActiveList: (api: UseGroupListResult | null) => void

    // factory for per-tab consumers
    /** Build the input object for `useGroupList`, for a given group. */
    getGroupListInput: (group: TaxonomicFilterGroup) => UseGroupListInput

    // value passthroughs
    value?: TaxonomicFilterValue

    // headless-component prop bags
    rootProps: { onKeyDown: (e: React.KeyboardEvent<any>) => void }
    inputProps: {
        value: string
        onChange: (e: React.ChangeEvent<HTMLInputElement>) => void
        onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void
        placeholder: string
    }
}

const PRE_INJECTED_META_TAB_ORDER: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.SuggestedFilters,
    TaxonomicFilterGroupType.RecentFilters,
    TaxonomicFilterGroupType.PinnedFilters,
]

function indexAfterLastMetaGroup(filtered: TaxonomicFilterGroupType[]): number {
    for (let i = PRE_INJECTED_META_TAB_ORDER.length - 1; i >= 0; i--) {
        const idx = filtered.indexOf(PRE_INJECTED_META_TAB_ORDER[i])
        if (idx !== -1) {
            return idx + 1
        }
    }
    return 0
}

/** Mirrors the legacy `taxonomicGroupTypes` selector. Resolves the consumer's
 *  request into a final ordered list of visible tabs by:
 *    1. Dropping types that aren't available in the current `groups`
 *    2. Resolving mutually-exclusive shortcut pairs (e.g. PageviewUrls vs
 *       PageviewEvents — keep the first, drop the second)
 *    3. Auto-injecting `RecentFilters` and `PinnedFilters` after the meta
 *       group block (Suggested → Recent → Pinned)
 *    4. Promoting shortcut groups (PageviewUrls / Screens / EmailAddresses
 *       / Elements when `$autocapture` is in `eventNames`) to right after
 *       the meta block.
 */
const MUTUALLY_EXCLUSIVE_PAIRS: [TaxonomicFilterGroupType, TaxonomicFilterGroupType][] = [
    [TaxonomicFilterGroupType.PageviewUrls, TaxonomicFilterGroupType.PageviewEvents],
    [TaxonomicFilterGroupType.Screens, TaxonomicFilterGroupType.ScreenEvents],
]

const AUTO_INJECT_META_GROUPS: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.RecentFilters,
    TaxonomicFilterGroupType.PinnedFilters,
]

const SHORTCUT_GROUPS_BASE: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.PageviewUrls,
    TaxonomicFilterGroupType.Screens,
    TaxonomicFilterGroupType.EmailAddresses,
]

function resolveTaxonomicGroupTypes(
    requested: TaxonomicFilterGroupType[],
    available: Set<TaxonomicFilterGroupType>,
    eventNames: string[]
): TaxonomicFilterGroupType[] {
    // 1. Mutual exclusion + availability filter
    const excluded = new Set<TaxonomicFilterGroupType>()
    for (const [a, b] of MUTUALLY_EXCLUSIVE_PAIRS) {
        if (requested.includes(a) && requested.includes(b)) {
            excluded.add(b)
        }
    }
    const filtered = requested.filter((t) => !excluded.has(t) && available.has(t))

    // 2. Auto-inject Recent / Pinned (Suggested stays opt-in)
    for (const metaType of AUTO_INJECT_META_GROUPS) {
        if (available.has(metaType) && !filtered.includes(metaType)) {
            filtered.splice(indexAfterLastMetaGroup(filtered), 0, metaType)
        }
    }

    // 3. Promote shortcut groups to right after the meta block
    const shortcutGroups: TaxonomicFilterGroupType[] = [
        ...SHORTCUT_GROUPS_BASE,
        ...(eventNames.includes('$autocapture') ? [TaxonomicFilterGroupType.Elements] : []),
    ]
    const toInsert: TaxonomicFilterGroupType[] = []
    for (const groupType of shortcutGroups) {
        const idx = filtered.indexOf(groupType)
        if (idx !== -1) {
            filtered.splice(idx, 1)
            toInsert.push(groupType)
        }
    }
    if (toInsert.length > 0) {
        filtered.splice(indexAfterLastMetaGroup(filtered), 0, ...toInsert)
    }

    return filtered
}

export function useTaxonomicFilter(opts: UseTaxonomicFilterOptions): TaxonomicFilterApi {
    const {
        taxonomicGroupTypes,
        value,
        onChange,
        onEnter,
        groupType: initialGroupType,
        searchQuery: controlledSearchQuery,
        initialSearchQuery,
        onSearchQueryChange,
        eventNames,
        schemaColumns,
        schemaColumnsLoading,
        metadataSource,
        suggestedFiltersLabel,
        excludedProperties,
        selectedProperties,
        propertyAllowList,
        maxContextOptions,
        hideBehavioralCohorts,
        endpointFilters,
        hogQLGlobals,
        hogQLExpressionShowBreakdownLabelHint,
        optionsFromProp,
        showNumericalPropsOnly,
        minSearchQueryLength,
        allowNonCapturedEvents,
        enableKeywordShortcuts,
        selectFirstItem,
        autoSelectItem,
    } = opts

    const ctx = useTaxonomicGroupsContext({
        eventNames,
        schemaColumns,
        schemaColumnsLoading,
        metadataSource,
        suggestedFiltersLabel,
        excludedProperties,
        propertyAllowList,
        selectedProperties,
        maxContextOptions,
        hideBehavioralCohorts,
        endpointFilters,
        hogQLGlobals,
        hogQLExpressionShowBreakdownLabelHint,
    })

    const allGroups = useMemo(() => buildTaxonomicGroups(ctx), [ctx])
    const allGroupTypes = useMemo(() => new Set(allGroups.map((g) => g.type)), [allGroups])
    const getLocalOverride = useTaxonomicLocalOverrides()

    const groupTypes = useMemo(
        () => resolveTaxonomicGroupTypes(taxonomicGroupTypes, allGroupTypes, eventNames ?? []),
        [taxonomicGroupTypes, allGroupTypes, eventNames]
    )

    const groups = useMemo(() => {
        const byType = new Map(allGroups.map((g) => [g.type, g]))
        return groupTypes.map((t) => byType.get(t)!).filter(Boolean)
    }, [allGroups, groupTypes])

    const metaGroupTypes = useMemo(
        () => new Set(groups.filter((g) => g.isMetaGroup || META_GROUP_TYPES.has(g.type)).map((g) => g.type)),
        [groups]
    )

    // ---- search query (controlled / uncontrolled) ---------------------------
    const [internalSearchQuery, setInternalSearchQuery] = useState(initialSearchQuery ?? '')
    const isSearchControlled = controlledSearchQuery !== undefined
    const searchQuery = isSearchControlled ? controlledSearchQuery : internalSearchQuery

    const setSearchQuery = useCallback(
        (q: string) => {
            if (!isSearchControlled) {
                setInternalSearchQuery(q)
            }
            onSearchQueryChange?.(q)
        },
        [isSearchControlled, onSearchQueryChange]
    )

    // ---- active group (controlled by initial prop, then internal) -----------
    const defaultActiveGroup = useMemo<TaxonomicFilterGroupType>(() => {
        if (initialGroupType && groupTypes.includes(initialGroupType)) {
            return initialGroupType
        }
        if (groupTypes.includes(TaxonomicFilterGroupType.SuggestedFilters)) {
            return TaxonomicFilterGroupType.SuggestedFilters
        }
        const firstNonMeta = groupTypes.find((t) => !metaGroupTypes.has(t))
        return firstNonMeta ?? groupTypes[0] ?? TaxonomicFilterGroupType.Empty
    }, [initialGroupType, groupTypes, metaGroupTypes])

    const [activeGroupType, setActiveGroupTypeInternal] = useState<TaxonomicFilterGroupType>(defaultActiveGroup)

    // If the resolved tab list shrinks beneath the active type, fall back.
    useEffect(() => {
        if (!groupTypes.includes(activeGroupType)) {
            setActiveGroupTypeInternal(defaultActiveGroup)
        }
    }, [groupTypes, activeGroupType, defaultActiveGroup])

    const setActiveGroupType = useCallback(
        (t: TaxonomicFilterGroupType) => {
            if (groupTypes.includes(t)) {
                setActiveGroupTypeInternal(t)
            }
        },
        [groupTypes]
    )

    const tabLeft = useCallback(() => {
        const idx = groupTypes.indexOf(activeGroupType)
        if (idx <= 0) {
            return
        }
        for (let i = idx - 1; i >= 0; i--) {
            setActiveGroupTypeInternal(groupTypes[i])
            return
        }
    }, [groupTypes, activeGroupType])

    const tabRight = useCallback(() => {
        const idx = groupTypes.indexOf(activeGroupType)
        if (idx === -1 || idx >= groupTypes.length - 1) {
            return
        }
        setActiveGroupTypeInternal(groupTypes[idx + 1])
    }, [groupTypes, activeGroupType])

    const activeGroup = useMemo(() => groups.find((g) => g.type === activeGroupType), [groups, activeGroupType])

    // ---- search placeholder -------------------------------------------------
    // Skip META groups (Recent/Pinned/Suggested/HogQL/etc.) — they exist
    // as shortcut surfaces, not as searchable content categories, and the
    // dropdown-menu rebuild now exposes Recent/Pinned as their own entries.
    // Listing them here just crowded the placeholder ("Search recent,
    // pinned, events…") and pushed real content labels out of the slice.
    const searchPlaceholder = useMemo(() => {
        const contentGroups = groups.filter((g) => !META_GROUP_TYPES.has(g.type))
        const labels = contentGroups
            .filter((g) => g.searchPlaceholder)
            .map((g) => g.searchPlaceholder as string)
            .slice(0, 3)
        return labels.length === 0 ? '' : labels.join(', ') + (contentGroups.length > 3 ? ' or other...' : '')
    }, [groups])

    // ---- active-list registration for keyboard nav --------------------------
    const activeListRef = useRef<UseGroupListResult | null>(null)
    const registerActiveList = useCallback((api: UseGroupListResult | null) => {
        activeListRef.current = api
    }, [])

    const selectItem = useCallback(
        (group: TaxonomicFilterGroup, valueIn: TaxonomicFilterValue | null, item: any) => {
            // Mirror the legacy `taxonomicFilterLogic.selectItem` recent
            // recording so menu commits show up in the dropdown's
            // "Recent" entry. Quick-filter items are skipped (they're
            // shortcuts, not filterable definitions); pinned/recent
            // context wrappers get stripped before persisting.
            if (valueIn != null && item && !isQuickFilterItem(item)) {
                const sourceGroupType = hasRecentContext(item) ? item._recentContext.sourceGroupType : group.type
                const stripped = hasRecentContext(item) ? stripRecentContext(item) : item
                const cleanItem = {
                    name: stripped.name,
                    ...(stripped.id ? { id: stripped.id } : {}),
                }
                const sourceGroupName = hasRecentContext(item) ? item._recentContext.sourceGroupName : group.name
                const propertyFilterFromRecent = hasRecentContext(item) ? item._recentContext.propertyFilter : undefined
                // Defer one tick — keeps the recents write off the
                // commit's render cycle so React doesn't re-render the
                // closing popover with a stale list.
                setTimeout(() => {
                    if (recentTaxonomicFiltersLogic.isMounted()) {
                        recentTaxonomicFiltersLogic.actions.recordRecentFilter(
                            sourceGroupType,
                            sourceGroupName,
                            valueIn,
                            cleanItem,
                            teamLogic.values.currentTeamId ?? undefined,
                            propertyFilterFromRecent
                        )
                    }
                }, 0)
            }
            onChange?.(group, valueIn, item)
            setSearchQuery('')
        },
        [onChange, setSearchQuery]
    )

    const selectSelected = useCallback(() => {
        const list = activeListRef.current
        const selected = list?.itemAtIndex()
        if (selected && activeGroup) {
            const itemValue = activeGroup.getValue?.(selected) ?? null
            selectItem(activeGroup, itemValue, selected)
        } else {
            onEnter?.(searchQuery)
        }
    }, [activeGroup, selectItem, onEnter, searchQuery])

    // ---- per-tab input factory ---------------------------------------------
    const getGroupListInput = useCallback(
        (group: TaxonomicFilterGroup): UseGroupListInput => ({
            group,
            searchQuery,
            optionsFromProp,
            showNumericalPropsOnly,
            hideBehavioralCohorts,
            minSearchQueryLength,
            allowNonCapturedEvents,
            enableKeywordShortcuts,
            selectFirstItem,
            autoSelectItem,
            // Logic-backed groups (Actions / Cohorts / Experiments / Dashboards
            // / Recent / Pinned) get their data via this bridge. Returns
            // undefined for groups whose data is `group.options` / endpoint /
            // optionsFromProp — useGroupList handles those internally.
            localOverride: getLocalOverride(group.type),
        }),
        [
            searchQuery,
            optionsFromProp,
            showNumericalPropsOnly,
            hideBehavioralCohorts,
            minSearchQueryLength,
            allowNonCapturedEvents,
            enableKeywordShortcuts,
            selectFirstItem,
            autoSelectItem,
            getLocalOverride,
        ]
    )

    // ---- keyboard handler --------------------------------------------------
    const onKeyDown = useCallback(
        (e: React.KeyboardEvent<any>) => {
            const list = activeListRef.current
            switch (e.key) {
                case 'ArrowUp':
                    list?.moveUp()
                    e.preventDefault()
                    break
                case 'ArrowDown':
                    list?.moveDown()
                    e.preventDefault()
                    break
                case 'Tab':
                    e.shiftKey ? tabLeft() : tabRight()
                    e.preventDefault()
                    break
                case 'Enter':
                    selectSelected()
                    e.preventDefault()
                    break
                case 'Escape':
                    setSearchQuery('')
                    e.preventDefault()
                    break
            }
        },
        [selectSelected, setSearchQuery, tabLeft, tabRight]
    )

    return {
        groups,
        groupTypes,
        metaGroupTypes,
        activeGroup,
        activeGroupType,
        setActiveGroupType,
        tabLeft,
        tabRight,
        searchQuery,
        setSearchQuery,
        searchPlaceholder,
        selectItem,
        selectSelected,
        registerActiveList,
        getGroupListInput,
        value,
        rootProps: { onKeyDown },
        inputProps: {
            value: searchQuery,
            onChange: (e) => setSearchQuery(e.target.value),
            onKeyDown,
            placeholder: searchPlaceholder ? `Search ${searchPlaceholder}` : 'Search',
        },
    }
}
