import {
    BuiltLogic,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import posthog from 'posthog-js'

import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'
import {
    hasRecentContext,
    recentTaxonomicFiltersLogic,
    stripRecentContext,
} from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import { hasPinnedContext } from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    DataWarehousePopoverField,
    ExcludedProperties,
    ListStorage,
    SelectedProperties,
    SkeletonItem,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
    isQuickFilterItem,
} from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'
import { isDefinitionStale } from 'lib/utils/definitions'
import { getEventDefinitionIcon, getPropertyDefinitionIcon } from 'scenes/data-management/events/DefinitionHeader'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { primaryEventPropertiesModel } from '~/models/primaryEventPropertiesModel'
import { updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { CoreFilterDefinition, EventDefinition, PropertyDefinition, TeamType } from '~/types'

import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from '../PropertyFilters/utils'
import { apmTaxonomicGroupsLogic } from './apmTaxonomicGroupsLogic'
import { cohortTaxonomicGroupsLogic } from './cohortTaxonomicGroupsLogic'
import { customEventsTaxonomicGroupsLogic } from './customEventsTaxonomicGroupsLogic'
import { dataWarehouseTaxonomicGroupsLogic } from './dataWarehouseTaxonomicGroupsLogic'
import { errorTrackingTaxonomicGroupsLogic } from './errorTrackingTaxonomicGroupsLogic'
import { eventMetadataTaxonomicGroupsLogic } from './eventMetadataTaxonomicGroupsLogic'
import { eventPropertiesTaxonomicGroupsLogic } from './eventPropertiesTaxonomicGroupsLogic'
import { eventsTaxonomicGroupsLogic } from './eventsTaxonomicGroupsLogic'
import { groupAnalyticsTaxonomicGroupsLogic } from './groupAnalyticsTaxonomicGroupsLogic'
import { hogQLExpressionTaxonomicGroupsLogic } from './hogQLExpressionTaxonomicGroupsLogic'
import { maxAIContextTaxonomicGroupsLogic } from './maxAIContextTaxonomicGroupsLogic'
import { miscTaxonomicGroupsLogic } from './miscTaxonomicGroupsLogic'
import { posthogResourcesTaxonomicGroupsLogic } from './posthogResourcesTaxonomicGroupsLogic'
import { propertyTabsTaxonomicGroupsLogic } from './propertyTabsTaxonomicGroupsLogic'
import { RECENT_PINNED_TAB_DEFINITIONS } from './recentPinnedTabDefinitions'
import { replayTaxonomicGroupsLogic } from './replayTaxonomicGroupsLogic'
import { revenueAnalyticsTaxonomicGroupsLogic } from './revenueAnalyticsTaxonomicGroupsLogic'
import { shortcutValueTaxonomicGroupsLogic } from './shortcutValueTaxonomicGroupsLogic'
import { suggestedFiltersTaxonomicGroupsLogic } from './suggestedFiltersTaxonomicGroupsLogic'
import type { taxonomicFilterLogicType } from './taxonomicFilterLogicType'

const PROPERTY_TAXONOMIC_GROUP_TYPES = new Set(Object.values(PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE))

export interface SelectItemMeta {
    position?: number
}

function indexAfterLastMetaGroup(
    filtered: TaxonomicFilterGroupType[],
    metaGroupOrder: TaxonomicFilterGroupType[]
): number {
    for (let i = metaGroupOrder.length - 1; i >= 0; i--) {
        const idx = filtered.indexOf(metaGroupOrder[i])
        if (idx !== -1) {
            return idx + 1
        }
    }
    return 0
}

const SHORTCUT_TO_PROPERTY_FILTER_GROUP_TYPES = new Set<TaxonomicFilterGroupType>([
    TaxonomicFilterGroupType.PageviewUrls,
    TaxonomicFilterGroupType.PageviewEvents,
    TaxonomicFilterGroupType.Screens,
    TaxonomicFilterGroupType.ScreenEvents,
    TaxonomicFilterGroupType.EmailAddresses,
    TaxonomicFilterGroupType.AutocaptureEvents,
])

export const DEFAULT_SLOTS_PER_GROUP = 5
export const MAX_TOP_MATCHES_PER_GROUP = 10

export const TRAFFIC_TYPE_VIRTUAL_PROPERTIES = [
    '$virt_is_bot',
    '$virt_traffic_type',
    '$virt_traffic_category',
    '$virt_bot_name',
]

const REDISTRIBUTION_PRIORITY_GROUPS: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.CustomEvents,
    TaxonomicFilterGroupType.PageviewUrls,
    TaxonomicFilterGroupType.Screens,
]

export type TopMatchItem = TaxonomicDefinitionTypes & { group: TaxonomicFilterGroupType }

export const SKELETON_ROWS_PER_GROUP = 3

export const REVEAL_BARRIER_TIMEOUT_MS = 5000

export { isSkeletonItem, type SkeletonItem } from 'lib/components/TaxonomicFilter/types'

export function redistributeTopMatches(
    items: TopMatchItem[],
    activeGroupCount: number,
    groupTypeOrder: TaxonomicFilterGroupType[] = []
): TopMatchItem[] {
    if (items.length === 0) {
        return []
    }

    const byGroup = new Map<TaxonomicFilterGroupType, TopMatchItem[]>()
    for (const item of items) {
        if (!byGroup.has(item.group)) {
            byGroup.set(item.group, [])
        }
        byGroup.get(item.group)!.push(item)
    }

    const allocated = new Map<TaxonomicFilterGroupType, TopMatchItem[]>()
    let usedSlots = 0
    for (const [groupType, groupItems] of byGroup) {
        const take = Math.min(groupItems.length, DEFAULT_SLOTS_PER_GROUP)
        allocated.set(groupType, groupItems.slice(0, take))
        usedSlots += take
    }

    if (byGroup.size < 3) {
        const totalSlots = DEFAULT_SLOTS_PER_GROUP * activeGroupCount
        let surplus = totalSlots - usedSlots
        if (surplus > 0) {
            const presentGroups = Array.from(byGroup.keys())
            const priorityOrder = [
                ...REDISTRIBUTION_PRIORITY_GROUPS.filter((g) => presentGroups.includes(g)),
                ...presentGroups.filter((g) => !REDISTRIBUTION_PRIORITY_GROUPS.includes(g)),
            ]

            for (const groupType of priorityOrder) {
                if (surplus <= 0) {
                    break
                }
                const groupItems = byGroup.get(groupType)!
                const currentlyAllocated = allocated.get(groupType) || []
                const remaining = groupItems.slice(currentlyAllocated.length, MAX_TOP_MATCHES_PER_GROUP)
                const extra = Math.min(remaining.length, surplus)
                if (extra > 0) {
                    allocated.set(groupType, [...currentlyAllocated, ...remaining.slice(0, extra)])
                    surplus -= extra
                }
            }
        }
    }

    const displayOrder =
        groupTypeOrder.length > 0 ? groupTypeOrder.filter((g) => allocated.has(g)) : Array.from(allocated.keys())

    const result: TopMatchItem[] = []
    for (const groupType of displayOrder) {
        const groupItems = allocated.get(groupType)
        if (groupItems) {
            result.push(...groupItems)
        }
    }

    return result
}

export const eventTaxonomicGroupProps: Pick<TaxonomicFilterGroup, 'getPopoverHeader' | 'getIcon'> = {
    getPopoverHeader: (eventDefinition: EventDefinition): string => {
        if (CORE_FILTER_DEFINITIONS_BY_GROUP.events[eventDefinition.name]) {
            return 'PostHog event'
        }
        return `${eventDefinition.verified ? 'Verified' : 'Unverified'} event`
    },
    getIcon: getEventDefinitionIcon,
}

export const propertyTaxonomicGroupProps = (
    coreDefinitionsGroup?: Record<string, CoreFilterDefinition>
): Pick<TaxonomicFilterGroup, 'getPopoverHeader' | 'getIcon'> => ({
    getPopoverHeader: (propertyDefinition: PropertyDefinition): string => {
        const coreGroup = coreDefinitionsGroup ?? CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties
        if (coreGroup[propertyDefinition.name]) {
            return 'PostHog property'
        }
        return 'Property'
    },
    getIcon: getPropertyDefinitionIcon,
})

export const defaultDataWarehousePopoverFields: DataWarehousePopoverField[] = [
    {
        key: 'id_field',
        label: 'ID Field',
    },
    {
        key: 'timestamp_field',
        label: 'Timestamp Field',
        allowHogQL: true,
    },
    {
        key: 'distinct_id_field',
        label: 'Distinct ID Field',
        allowHogQL: true,
    },
]

export const taxonomicFilterLogic = kea<taxonomicFilterLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path(['lib', 'components', 'TaxonomicFilter', 'taxonomicFilterLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId', 'currentTeam'],
            projectLogic,
            ['currentProjectId'],
            groupAnalyticsTaxonomicGroupsLogic,
            ['groupAnalyticsTaxonomicGroups', 'groupAnalyticsTaxonomicGroupNames'],
            cohortTaxonomicGroupsLogic,
            ['cohortTaxonomicGroups'],
            hogQLExpressionTaxonomicGroupsLogic,
            ['hogQLExpressionTaxonomicGroups'],
            eventMetadataTaxonomicGroupsLogic,
            ['eventMetadataTaxonomicGroups'],
            maxAIContextTaxonomicGroupsLogic,
            ['maxAIContextTaxonomicGroups'],
            suggestedFiltersTaxonomicGroupsLogic,
            ['suggestedFiltersTaxonomicGroups'],
            apmTaxonomicGroupsLogic,
            ['apmTaxonomicGroups'],
            replayTaxonomicGroupsLogic,
            ['replayTaxonomicGroups'],
            posthogResourcesTaxonomicGroupsLogic,
            ['posthogResourcesTaxonomicGroups'],
            errorTrackingTaxonomicGroupsLogic,
            ['errorTrackingTaxonomicGroups'],
            revenueAnalyticsTaxonomicGroupsLogic,
            ['revenueAnalyticsTaxonomicGroups'],
            dataWarehouseTaxonomicGroupsLogic,
            ['dataWarehouseTaxonomicGroups'],
            shortcutValueTaxonomicGroupsLogic,
            ['shortcutValueTaxonomicGroups'],
            eventsTaxonomicGroupsLogic,
            ['eventsTaxonomicGroups'],
            customEventsTaxonomicGroupsLogic,
            ['customEventsTaxonomicGroups'],
            eventPropertiesTaxonomicGroupsLogic,
            ['eventPropertiesTaxonomicGroups'],
            propertyTabsTaxonomicGroupsLogic,
            ['featureFlagPropertyTaxonomicGroups', 'numericalAndPersonPropertyTaxonomicGroups'],
            miscTaxonomicGroupsLogic,
            [
                'activityWorkflowActionsTaxonomicGroups',
                'elementsMetadataTaxonomicGroups',
                'wildcardsPersonsTaxonomicGroups',
                'sessionPropertiesTaxonomicGroups',
            ],
        ],
        actions: [primaryEventPropertiesModel, ['ensureLoadedForEvents']],
    })),
    actions(() => ({
        moveUp: true,
        moveDown: true,
        selectSelected: true,
        enableMouseInteractions: true,
        tabLeft: true,
        tabRight: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        markUserInteraction: true,
        recordPaste: (pastedLength: number) => ({ pastedLength }),
        setActiveTab: (activeTab: TaxonomicFilterGroupType) => ({ activeTab }),
        selectItem: (
            group: TaxonomicFilterGroup,
            value: TaxonomicFilterValue | null,
            item: any,
            meta?: SelectItemMeta
        ) => ({
            group,
            value,
            item,
            meta,
        }),
        infiniteListResultsReceived: (groupType: TaxonomicFilterGroupType, results: ListStorage) => ({
            groupType,
            results,
        }),
        appendTopMatches: (items: (TaxonomicDefinitionTypes & { group: TaxonomicFilterGroupType })[]) => ({
            items,
        }),
        openRevealBarrier: true,
        setIncludeStaleEvents: (includeStaleEvents: boolean) => ({ includeStaleEvents }),
    })),
    reducers(({ props, selectors }) => ({
        searchQuery: [
            props.initialSearchQuery || '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
            },
        ],
        activeTab: [
            (state: any): TaxonomicFilterGroupType => {
                const groupTypes = selectors.taxonomicGroupTypes(state)
                const propsGroupType = selectors.groupType(state)
                // If there's an existing filter type (e.g., SQL expression being edited),
                // use that instead of defaulting to SuggestedFilters
                if (propsGroupType && groupTypes.includes(propsGroupType)) {
                    return propsGroupType
                }
                if (groupTypes.includes(TaxonomicFilterGroupType.SuggestedFilters)) {
                    return TaxonomicFilterGroupType.SuggestedFilters
                }
                const metaTypes = selectors.metaGroupTypes(state)
                return groupTypes.find((t) => !metaTypes.has(t)) ?? groupTypes[0]
            },
            {
                setActiveTab: (_, { activeTab }) => activeTab,
            },
        ],
        mouseInteractionsEnabled: [
            // This fixes a bug with keyboard up/down scrolling when the mouse is over the list.
            // Otherwise shifting list elements cause the "hover" action to be triggered randomly.
            true,
            {
                moveUp: () => false,
                moveDown: () => false,
                setActiveTab: () => true,
                enableMouseInteractions: () => true,
            },
        ],
        hadInteraction: [
            // Any genuine user-driven action flips this. Read in `beforeUnmount` to gate the
            // `taxonomic filter closed` capture so involuntary mounts (popovers/side panels
            // rendered before the picker is shown, route transitions) don't fire phantom closes.
            // New interaction sources should be added here, not by mutating cache from listeners.
            false,
            {
                moveUp: () => true,
                moveDown: () => true,
                tabLeft: () => true,
                tabRight: () => true,
                setActiveTab: () => true,
                selectItem: () => true,
                markUserInteraction: () => true,
            },
        ],
        topMatchItems: [
            [] as (TaxonomicDefinitionTypes & { group: TaxonomicFilterGroupType })[],
            {
                setSearchQuery: () => [],
                appendTopMatches: (
                    state: (TaxonomicDefinitionTypes & { group: TaxonomicFilterGroupType })[],
                    { items }: { items: (TaxonomicDefinitionTypes & { group: TaxonomicFilterGroupType })[] }
                ) => {
                    const incomingGroup = items[0]?.group
                    if (!incomingGroup) {
                        return state
                    }
                    return [...state.filter((i) => i.group !== incomingGroup), ...items]
                },
            },
        ],
        revealBarrierOpen: [
            // Gates the SuggestedFilters tab on every fresh search: once a search starts we
            // hide all non-meta group contributions behind skeletons until either every group
            // resolves or the 5s timer fires (see setSearchQuery listener). This stops rows
            // from jumping around as slower groups settle on top of faster ones.
            !(props.initialSearchQuery ?? '').trim(),
            {
                setSearchQuery: (_, { searchQuery }: { searchQuery: string }) => !(searchQuery ?? '').trim(),
                openRevealBarrier: () => true,
            },
        ],
        includeStaleEvents: [
            // Per-session opt-in to surface event definitions whose last ingested occurrence
            // is older than STALE_EVENT_DAYS. Resets back to false on every fresh search so
            // the user re-opts in deliberately rather than carrying stale results across
            // unrelated queries.
            false,
            {
                setIncludeStaleEvents: (_, { includeStaleEvents }: { includeStaleEvents: boolean }) =>
                    includeStaleEvents,
                setSearchQuery: () => false,
                setActiveTab: () => false,
            },
        ],
    })),
    selectors({
        selectedItemMeta: [() => [(_, props) => props.filter], (filter) => filter],
        showNumericalPropsOnly: [
            () => [(_, props) => props.showNumericalPropsOnly],
            (showNumericalPropsOnly) => showNumericalPropsOnly ?? false,
        ],
        taxonomicFilterLogicKey: [
            (_, p) => [p.taxonomicFilterLogicKey],
            (taxonomicFilterLogicKey) => taxonomicFilterLogicKey,
        ],
        eventNames: [() => [(_, props) => props.eventNames], (eventNames) => eventNames ?? []],
        // Combined into a single selector so taxonomicGroups stays under kea's 16-dep
        // tuple type limit; consumers spread directly.
        allGroupAnalyticsTaxonomicGroups: [
            (s) => [s.groupAnalyticsTaxonomicGroups, s.groupAnalyticsTaxonomicGroupNames],
            (
                groupAnalyticsTaxonomicGroups: TaxonomicFilterGroup[],
                groupAnalyticsTaxonomicGroupNames: TaxonomicFilterGroup[]
            ): TaxonomicFilterGroup[] => [...groupAnalyticsTaxonomicGroups, ...groupAnalyticsTaxonomicGroupNames],
        ],
        // Bundles the meta-group tabs into one selector input so taxonomicGroups stays
        // under kea's 16-dep tuple type limit.
        allMetaTaxonomicGroups: [
            (s) => [s.suggestedFiltersTaxonomicGroups],
            (suggestedFiltersTaxonomicGroups: TaxonomicFilterGroup[]): TaxonomicFilterGroup[] => [
                ...suggestedFiltersTaxonomicGroups,
                ...RECENT_PINNED_TAB_DEFINITIONS,
            ],
        ],
        dataWarehousePopoverFields: [
            () => [(_, props) => props.dataWarehousePopoverFields],
            (dataWarehousePopoverFields) => dataWarehousePopoverFields ?? [],
        ],
        excludedProperties: [
            () => [(_, props) => props.excludedProperties],
            (excludedProperties) => (excludedProperties ?? {}) as ExcludedProperties,
        ],
        selectedProperties: [
            () => [(_, props) => props.selectedProperties],
            (selectedProperties) => (selectedProperties ?? {}) as SelectedProperties,
        ],
        propertyAllowList: [
            () => [(_, props) => props.propertyAllowList],
            (propertyAllowList) => propertyAllowList as TaxonomicFilterLogicProps['propertyAllowList'],
        ],
        propertyFilters: [
            (s) => [s.excludedProperties, s.propertyAllowList],
            (excludedProperties, propertyAllowList) => ({ excludedProperties, propertyAllowList }),
        ],
        allowNonCapturedEvents: [
            () => [(_, props) => props.allowNonCapturedEvents],
            (allowNonCapturedEvents: boolean | undefined) => allowNonCapturedEvents ?? false,
        ],
        hideBehavioralCohorts: [
            () => [(_, props) => props.hideBehavioralCohorts],
            (hideBehavioralCohorts: boolean | undefined) => hideBehavioralCohorts ?? false,
        ],
        taxonomicGroups: [
            (s) => [
                s.currentTeam,
                s.currentProjectId,
                s.allGroupAnalyticsTaxonomicGroups,
                s.eventNames,
                s.dataWarehouseTaxonomicGroups,
                s.hogQLExpressionTaxonomicGroups,
                s.allMetaTaxonomicGroups,
                s.propertyFilters,
                s.eventMetadataTaxonomicGroups,
                s.maxAIContextTaxonomicGroups,
                s.cohortTaxonomicGroups,
                s.apmTaxonomicGroups,
                s.eventPropertiesTaxonomicGroups,
                s.featureFlagPropertyTaxonomicGroups,
                s.numericalAndPersonPropertyTaxonomicGroups,
                s.activityWorkflowActionsTaxonomicGroups,
                s.elementsMetadataTaxonomicGroups,
                s.wildcardsPersonsTaxonomicGroups,
                s.sessionPropertiesTaxonomicGroups,
                s.replayTaxonomicGroups,
                s.posthogResourcesTaxonomicGroups,
                s.errorTrackingTaxonomicGroups,
                s.revenueAnalyticsTaxonomicGroups,
                s.shortcutValueTaxonomicGroups,
                s.eventsTaxonomicGroups,
                s.customEventsTaxonomicGroups,
            ],
            (
                currentTeam: TeamType,
                projectId: number | null,
                allGroupAnalyticsTaxonomicGroups: TaxonomicFilterGroup[],
                eventNames: string[],
                dataWarehouseTaxonomicGroups: TaxonomicFilterGroup[],
                hogQLExpressionTaxonomicGroups: TaxonomicFilterGroup[],
                allMetaTaxonomicGroups: TaxonomicFilterGroup[],
                propertyFilters,
                eventMetadataTaxonomicGroups: TaxonomicFilterGroup[],
                maxAIContextTaxonomicGroups: TaxonomicFilterGroup[],
                cohortTaxonomicGroups: TaxonomicFilterGroup[],
                apmTaxonomicGroups: TaxonomicFilterGroup[],
                eventPropertiesTaxonomicGroups: TaxonomicFilterGroup[],
                featureFlagPropertyTaxonomicGroups: TaxonomicFilterGroup[],
                numericalAndPersonPropertyTaxonomicGroups: TaxonomicFilterGroup[],
                activityWorkflowActionsTaxonomicGroups: TaxonomicFilterGroup[],
                elementsMetadataTaxonomicGroups: TaxonomicFilterGroup[],
                wildcardsPersonsTaxonomicGroups: TaxonomicFilterGroup[],
                sessionPropertiesTaxonomicGroups: TaxonomicFilterGroup[],
                replayTaxonomicGroups: TaxonomicFilterGroup[],
                posthogResourcesTaxonomicGroups: TaxonomicFilterGroup[],
                errorTrackingTaxonomicGroups: TaxonomicFilterGroup[],
                revenueAnalyticsTaxonomicGroups: TaxonomicFilterGroup[],
                shortcutValueTaxonomicGroups: TaxonomicFilterGroup[],
                eventsTaxonomicGroups: TaxonomicFilterGroup[],
                customEventsTaxonomicGroups: TaxonomicFilterGroup[]
            ): TaxonomicFilterGroup[] => {
                const groups: TaxonomicFilterGroup[] = [
                    ...eventsTaxonomicGroups,
                    ...activityWorkflowActionsTaxonomicGroups,
                    ...dataWarehouseTaxonomicGroups,
                    ...elementsMetadataTaxonomicGroups,
                    ...eventPropertiesTaxonomicGroups,
                    ...eventMetadataTaxonomicGroups,
                    ...featureFlagPropertyTaxonomicGroups,
                    ...errorTrackingTaxonomicGroups,
                    ...revenueAnalyticsTaxonomicGroups,
                    ...apmTaxonomicGroups,
                    ...numericalAndPersonPropertyTaxonomicGroups,
                    ...cohortTaxonomicGroups,
                    ...shortcutValueTaxonomicGroups,
                    ...customEventsTaxonomicGroups,
                    ...wildcardsPersonsTaxonomicGroups,
                    ...posthogResourcesTaxonomicGroups,
                    ...sessionPropertiesTaxonomicGroups,
                    ...hogQLExpressionTaxonomicGroups,
                    ...replayTaxonomicGroups,
                    ...maxAIContextTaxonomicGroups,
                    ...allMetaTaxonomicGroups,
                    ...allGroupAnalyticsTaxonomicGroups,
                ]

                return groups
            },
        ],
        activeTaxonomicGroup: [
            (s) => [s.activeTab, s.taxonomicGroups],
            (activeTab, taxonomicGroups) => taxonomicGroups.find((g) => g.type === activeTab),
        ],
        metaGroupTypes: [
            (s) => [s.taxonomicGroups],
            (taxonomicGroups: TaxonomicFilterGroup[]): Set<string> =>
                new Set(taxonomicGroups.filter((g) => g.isMetaGroup).map((g) => g.type)),
        ],
        taxonomicGroupTypes: [
            (s, p) => [p.taxonomicGroupTypes, s.taxonomicGroups, s.eventNames],
            (groupTypes, taxonomicGroups, eventNames): TaxonomicFilterGroupType[] => {
                const availableGroupTypes = new Set(taxonomicGroups.map((group) => group.type))
                const resolvedGroupTypes: TaxonomicFilterGroupType[] =
                    groupTypes || taxonomicGroups.map((group) => group.type)

                const mutuallyExclusivePairs: [TaxonomicFilterGroupType, TaxonomicFilterGroupType][] = [
                    [TaxonomicFilterGroupType.PageviewUrls, TaxonomicFilterGroupType.PageviewEvents],
                    [TaxonomicFilterGroupType.Screens, TaxonomicFilterGroupType.ScreenEvents],
                ]
                const excluded = new Set<TaxonomicFilterGroupType>()
                for (const [a, b] of mutuallyExclusivePairs) {
                    if (resolvedGroupTypes.includes(a) && resolvedGroupTypes.includes(b)) {
                        console.warn(`TaxonomicFilter: ${a} and ${b} are mutually exclusive, ignoring ${b}`)
                        excluded.add(b)
                    }
                }

                const filtered = resolvedGroupTypes.filter((groupType) => {
                    if (excluded.has(groupType)) {
                        return false
                    }
                    return availableGroupTypes.has(groupType)
                })

                // SuggestedFilters must be explicitly requested; RecentFilters and
                // PinnedFilters are auto-injected after existing meta groups.
                const metaGroupOrder = [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.RecentFilters,
                    TaxonomicFilterGroupType.PinnedFilters,
                ]
                const autoInjectGroups = [
                    TaxonomicFilterGroupType.RecentFilters,
                    TaxonomicFilterGroupType.PinnedFilters,
                ]
                for (const metaType of autoInjectGroups) {
                    if (availableGroupTypes.has(metaType) && !filtered.includes(metaType)) {
                        filtered.splice(indexAfterLastMetaGroup(filtered, metaGroupOrder), 0, metaType)
                    }
                }

                // Promote shortcut groups to top positions (after meta groups)
                const shortcutGroups: TaxonomicFilterGroupType[] = [
                    TaxonomicFilterGroupType.PageviewUrls,
                    TaxonomicFilterGroupType.Screens,
                    TaxonomicFilterGroupType.EmailAddresses,
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
                    filtered.splice(indexAfterLastMetaGroup(filtered, metaGroupOrder), 0, ...toInsert)
                }

                return filtered
            },
        ],
        infiniteListLogics: [
            (s) => [s.taxonomicGroupTypes, (_, props) => props],
            (taxonomicGroupTypes, props): Record<string, BuiltLogic<infiniteListLogicType>> =>
                Object.fromEntries(
                    taxonomicGroupTypes.map((groupType) => [
                        groupType,
                        infiniteListLogic.build({
                            ...props,
                            listGroupType: groupType,
                        }),
                    ])
                ),
        ],
        anyGroupLoading: [
            (s) => [
                (state, props) => {
                    const logics = s.infiniteListLogics(state, props)
                    const meta = s.metaGroupTypes(state, props)
                    return Object.entries(logics).some(
                        ([type, logic]) =>
                            !meta.has(type) && logic.isMounted() && logic.selectors.isLoading(state, logic.props)
                    )
                },
            ],
            (anyGroupLoading: boolean) => anyGroupLoading,
        ],
        loadingGroupTypes: [
            (s) => [
                (state, props) => {
                    const logics = s.infiniteListLogics(state, props)
                    const meta = s.metaGroupTypes(state, props)
                    return Object.entries(logics)
                        .filter(
                            ([type, logic]) =>
                                !meta.has(type) && logic.isMounted() && logic.selectors.isLoading(state, logic.props)
                        )
                        .map(([type]) => type)
                        .join(',')
                },
            ],
            (loadingGroupTypesString: string): TaxonomicFilterGroupType[] =>
                loadingGroupTypesString ? (loadingGroupTypesString.split(',') as TaxonomicFilterGroupType[]) : [],
        ],
        infiniteListCounts: [
            (s) => [
                (state, props) =>
                    Object.fromEntries(
                        Object.entries(s.infiniteListLogics(state, props)).map(([groupType, logic]) => [
                            groupType,
                            logic.isMounted() ? logic.selectors.totalListCount(state, logic.props) : 0,
                        ])
                    ),
            ],
            (infiniteListCounts) => infiniteListCounts,
            { resultEqualityCheck: objectsEqual },
        ],
        value: [() => [(_, props) => props.value], (value) => value],
        groupType: [() => [(_, props) => props.groupType], (groupType) => groupType],
        currentTabIndex: [
            (s) => [s.taxonomicGroupTypes, s.activeTab],
            (groupTypes, activeTab) => Math.max(groupTypes.indexOf(activeTab || ''), 0),
        ],
        searchPlaceholder: [
            (s) => [s.taxonomicGroups, s.taxonomicGroupTypes],
            (allTaxonomicGroups, searchGroupTypes) => {
                if (searchGroupTypes.length > 1) {
                    searchGroupTypes = searchGroupTypes.filter(
                        (type) =>
                            !type.startsWith(TaxonomicFilterGroupType.GroupsPrefix) &&
                            !type.startsWith(TaxonomicFilterGroupType.GroupNamesPrefix)
                    )
                }
                const names = searchGroupTypes
                    .map((type) => {
                        const taxonomicGroup = allTaxonomicGroups.find(
                            (tGroup) => tGroup.type == type
                        ) as TaxonomicFilterGroup
                        return taxonomicGroup.searchPlaceholder
                    })
                    .filter(Boolean)
                return names
                    .filter((a) => !!a)
                    .map(
                        (name, index) =>
                            `${index !== 0 ? (index === searchGroupTypes.length - 1 ? ' or ' : ', ') : ''}${name}`
                    )
                    .join('')
            },
        ],
        redistributedTopMatchItems: [
            (s) => [s.topMatchItems, s.taxonomicGroupTypes, s.metaGroupTypes],
            (
                topMatchItems: TopMatchItem[],
                taxonomicGroupTypes: TaxonomicFilterGroupType[],
                metaGroupTypes: Set<string>
            ): TopMatchItem[] => {
                const nonMetaGroups = taxonomicGroupTypes.filter((t) => !metaGroupTypes.has(t))
                return redistributeTopMatches(topMatchItems, nonMetaGroups.length, nonMetaGroups)
            },
        ],
        topMatchItemsWithSkeletons: [
            (s) => [
                s.redistributedTopMatchItems,
                s.taxonomicGroupTypes,
                s.loadingGroupTypes,
                s.taxonomicGroups,
                s.searchQuery,
                s.metaGroupTypes,
                s.revealBarrierOpen,
            ],
            (
                redistributed: TopMatchItem[],
                taxonomicGroupTypes: TaxonomicFilterGroupType[],
                loadingGroupTypes: TaxonomicFilterGroupType[],
                taxonomicGroups: TaxonomicFilterGroup[],
                searchQuery: string,
                metaGroupTypes: Set<string>,
                revealBarrierOpen: boolean
            ): (TopMatchItem | SkeletonItem)[] => {
                if (!searchQuery) {
                    return redistributed
                }

                const nonMetaGroups = taxonomicGroupTypes.filter((t) => !metaGroupTypes.has(t))

                const buildSkeletons = (groupType: TaxonomicFilterGroupType): SkeletonItem[] => {
                    const groupDef = taxonomicGroups.find((g) => g.type === groupType)
                    const groupName = groupDef?.name ?? groupType
                    const skeletons: SkeletonItem[] = []
                    for (let i = 0; i < SKELETON_ROWS_PER_GROUP; i++) {
                        skeletons.push({ _skeleton: true, group: groupType, groupName })
                    }
                    return skeletons
                }

                // Pre-barrier: every non-meta group renders as a skeleton — even ones that
                // already resolved — so we don't reveal partial results that would shift
                // when a slower group finishes.
                if (!revealBarrierOpen) {
                    const result: SkeletonItem[] = []
                    for (const groupType of nonMetaGroups) {
                        result.push(...buildSkeletons(groupType))
                    }
                    return result
                }

                const result: (TopMatchItem | SkeletonItem)[] = []
                for (const groupType of nonMetaGroups) {
                    const groupItems = redistributed.filter((item) => item.group === groupType)
                    if (groupItems.length > 0) {
                        result.push(...groupItems)
                    } else if (loadingGroupTypes.includes(groupType)) {
                        result.push(...buildSkeletons(groupType))
                    }
                }
                return result
            },
        ],
    }),
    afterMount(({ actions, props, cache }) => {
        cache.openedAt = Date.now()
        cache.hadSelection = false
        // Initial fire — the model dedupes against taxonomy defaults and already-loaded names.
        if (props.eventNames?.length) {
            actions.ensureLoadedForEvents(props.eventNames)
        }
        // If we land with an initial search query (e.g. deep-linked filter), arm the same
        // 5s reveal-barrier timer as a normal keystroke would — the `setSearchQuery`
        // listener doesn't run on mount because no action was dispatched.
        if ((props.initialSearchQuery ?? '').trim()) {
            cache.disposables.add(() => {
                const timerId = window.setTimeout(() => actions.openRevealBarrier(), REVEAL_BARRIER_TIMEOUT_MS)
                return () => window.clearTimeout(timerId)
            }, 'revealBarrierTimer')
        }
    }),
    beforeUnmount(({ values, cache }) => {
        // Only capture when there's evidence the user actually engaged with the picker. The logic
        // mounts in many places where the picker isn't visibly opened (popover contents rendered
        // before the popover shows, side panels tied to scene lifecycle, route transitions), so
        // without this gate every involuntary mount/unmount fires a close with hadSelection=false
        // and inflates the abandonment metric (top sessions hit 100+ closes pre-gate).
        if (values.hadInteraction) {
            posthog.capture('taxonomic filter closed', {
                dwellMs: Date.now() - (cache.openedAt ?? Date.now()),
                hadSelection: !!cache.hadSelection,
                groupType: values.activeTab,
            })
        }
    }),
    propsChanged(({ actions, props }, oldProps) => {
        // When the in-context events change (e.g. an insight series swaps event), ask the model
        // to load any team-configured primary properties for those names.
        if (props.eventNames !== oldProps.eventNames && props.eventNames?.length) {
            actions.ensureLoadedForEvents(props.eventNames)
        }
    }),
    listeners(({ actions, values, props, cache }) => ({
        selectItem: ({ group, value, item, meta }) => {
            if (item) {
                const sourceGroupType = hasRecentContext(item) ? item._recentContext.sourceGroupType : group.type
                const hadSearchInput = !!values.searchQuery
                const wasQuickFilter = isQuickFilterItem(item)
                const wasFromRecents = hasRecentContext(item)
                const wasFromPinnedList = hasPinnedContext(item)

                const isEventTab =
                    sourceGroupType === TaxonomicFilterGroupType.Events ||
                    sourceGroupType === TaxonomicFilterGroupType.CustomEvents
                const wasStale =
                    isEventTab && item && typeof item === 'object' && 'last_seen_at' in item
                        ? isDefinitionStale(item)
                        : undefined

                posthog.capture('taxonomic filter item selected', {
                    groupType: values.activeTab,
                    sourceGroupType,
                    wasFromPinnedList,
                    wasFromRecents,
                    wasQuickFilter,
                    hadSearchInput,
                    position: meta?.position,
                    query: values.searchQuery || undefined,
                    wasStale,
                    ...(wasQuickFilter && {
                        filterName: item.name,
                        propertyKey: item.propertyKey,
                        operator: item.operator,
                        filterValue: item.filterValue,
                        propertyFilterType: item.propertyFilterType,
                        eventName: item.eventName,
                    }),
                })

                // Record to recents (deferred to avoid render loop).
                // Record here when:
                //   - the consumer says the selection is final (selectingKeyOnly), or
                //   - we're re-clicking a recent that already has a complete propertyFilter, or
                //   - this isn't a property-style group (so propertyFilterLogic isn't going to record it).
                // QuickFilterItem shortcuts are synthetic, never recorded.
                const hasCompletePropertyFilter = hasRecentContext(item) && item._recentContext.propertyFilter
                const isPropertyFilterLogicGroup =
                    PROPERTY_TAXONOMIC_GROUP_TYPES.has(sourceGroupType) ||
                    SHORTCUT_TO_PROPERTY_FILTER_GROUP_TYPES.has(sourceGroupType) ||
                    sourceGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix)
                const recordHereNow = props.selectingKeyOnly || hasCompletePropertyFilter || !isPropertyFilterLogicGroup

                if (recordHereNow && !isQuickFilterItem(item)) {
                    setTimeout(() => {
                        if (recentTaxonomicFiltersLogic.isMounted()) {
                            const stripped = hasRecentContext(item) ? stripRecentContext(item) : item
                            const cleanItem = { name: stripped.name, ...(stripped.id ? { id: stripped.id } : {}) }
                            const sourceGroupName = hasRecentContext(item)
                                ? item._recentContext.sourceGroupName
                                : group.name
                            const propertyFilterFromRecent =
                                !props.selectingKeyOnly && hasRecentContext(item)
                                    ? item._recentContext.propertyFilter
                                    : undefined
                            recentTaxonomicFiltersLogic.actions.recordRecentFilter({
                                groupType: sourceGroupType,
                                groupName: sourceGroupName,
                                value,
                                item: cleanItem,
                                teamId: teamLogic.values.currentTeamId ?? undefined,
                                propertyFilter: propertyFilterFromRecent,
                                selectingKeyOnly: !!props.selectingKeyOnly,
                            })
                        }
                    }, 0)
                }

                cache.hadSelection = true
                props.onChange?.(group, value, item)
            } else if (group.type === TaxonomicFilterGroupType.HogQLExpression && value) {
                cache.hadSelection = true
                props.onChange?.(group, value, item)
            } else if (props.onEnter) {
                props.onEnter(values.searchQuery)
                return
            }
            actions.setSearchQuery('')
        },

        moveUp: async (_, breakpoint) => {
            if (values.activeTab) {
                infiniteListLogic({
                    ...props,
                    listGroupType: values.activeTab,
                }).actions.moveUp()
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        moveDown: async (_, breakpoint) => {
            if (values.activeTab) {
                infiniteListLogic({
                    ...props,
                    listGroupType: values.activeTab,
                }).actions.moveDown()
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        selectSelected: async (_, breakpoint) => {
            if (values.activeTab) {
                infiniteListLogic({
                    ...props,
                    listGroupType: values.activeTab,
                }).actions.selectSelected()
            }
            await breakpoint(100)
            actions.enableMouseInteractions()
        },

        tabLeft: () => {
            const { currentTabIndex, taxonomicGroupTypes, infiniteListCounts } = values
            for (let i = 1; i < taxonomicGroupTypes.length; i++) {
                const newIndex = (currentTabIndex - i + taxonomicGroupTypes.length) % taxonomicGroupTypes.length
                if (infiniteListCounts[taxonomicGroupTypes[newIndex]] > 0) {
                    actions.setActiveTab(taxonomicGroupTypes[newIndex])
                    return
                }
            }
        },

        tabRight: () => {
            const { currentTabIndex, taxonomicGroupTypes, infiniteListCounts } = values
            for (let i = 1; i < taxonomicGroupTypes.length; i++) {
                const newIndex = (currentTabIndex + i) % taxonomicGroupTypes.length
                if (infiniteListCounts[taxonomicGroupTypes[newIndex]] > 0) {
                    actions.setActiveTab(taxonomicGroupTypes[newIndex])
                    return
                }
            }
        },

        recordPaste: ({ pastedLength }) => {
            cache.pastedCharsSinceLastCapture = (cache.pastedCharsSinceLastCapture ?? 0) + Math.max(0, pastedLength)
        },

        setSearchQuery: async ({ searchQuery }, breakpoint) => {
            const { activeTaxonomicGroup } = values

            // Re-arm the reveal barrier timer on every keystroke. The reducer has already
            // closed the barrier (when searchQuery is non-empty) — the timer fallback opens
            // it again after 5s if not all groups have completed. Re-adding under the same
            // key auto-disposes the previous timer; we only need to explicitly dispose when
            // the query clears (no fresh timer to schedule).
            if ((searchQuery ?? '').trim()) {
                cache.disposables.add(() => {
                    const timerId = window.setTimeout(() => actions.openRevealBarrier(), REVEAL_BARRIER_TIMEOUT_MS)
                    return () => window.clearTimeout(timerId)
                }, 'revealBarrierTimer')
            } else {
                cache.disposables.dispose('revealBarrierTimer')
            }

            await breakpoint(500)
            const pastedChars = cache.pastedCharsSinceLastCapture ?? 0
            cache.pastedCharsSinceLastCapture = 0
            if (searchQuery) {
                const totalLength = searchQuery.length
                const inputMode: 'pasted' | 'mixed' | 'typed' =
                    pastedChars >= totalLength && pastedChars > 0 ? 'pasted' : pastedChars > 0 ? 'mixed' : 'typed'
                posthog.capture('taxonomic_filter_search_query', {
                    searchQuery,
                    groupType: activeTaxonomicGroup?.type,
                    inputMode,
                    pastedFraction: totalLength > 0 ? Math.min(1, pastedChars / totalLength) : 0,
                    excludeStale: !values.includeStaleEvents,
                })
            }
        },

        setIncludeStaleEvents: ({ includeStaleEvents }) => {
            posthog.capture('taxonomic filter include stale toggled', {
                includeStaleEvents,
                groupType: values.activeTab,
                searchQuery: values.searchQuery || undefined,
            })
        },

        infiniteListResultsReceived: async ({ groupType, results }, breakpoint) => {
            if (groupType && !values.metaGroupTypes.has(groupType)) {
                const subLogic = values.infiniteListLogics[groupType]
                if (subLogic?.isMounted()) {
                    const matches = subLogic.values.topMatchesForQuery
                        .filter(Boolean)
                        .map((m) => ({ ...m, group: groupType }))
                    if (matches.length > 0) {
                        actions.appendTopMatches(matches)
                    }
                }
            }

            // Update app-wide cached property metadata
            if (
                results.count > 0 &&
                (groupType === TaxonomicFilterGroupType.EventProperties ||
                    groupType === TaxonomicFilterGroupType.PersonProperties ||
                    groupType === TaxonomicFilterGroupType.NumericalEventProperties)
            ) {
                const propertyDefinitions: PropertyDefinition[] = results.results as PropertyDefinition[]
                const apiType = groupType === TaxonomicFilterGroupType.PersonProperties ? 'person' : 'event'
                const newPropertyDefinitions = Object.fromEntries(
                    propertyDefinitions.map((propertyDefinition) => [
                        `${apiType}/${propertyDefinition.name}`,
                        propertyDefinition,
                    ])
                )
                updatePropertyDefinitions(newPropertyDefinitions)
            }

            // Yield a microtask so all sibling `infiniteListResultsReceived` and
            // `loadRemoteItems` dispatches triggered by the same `setSearchQuery` have
            // settled — otherwise a local-only group firing synchronously would see
            // `anyGroupLoading=false` before remote siblings have started loading.
            await breakpoint(0)
            if (values.searchQuery && !values.revealBarrierOpen && !values.anyGroupLoading) {
                cache.disposables.dispose('revealBarrierTimer')
                actions.openRevealBarrier()
            }
        },
    })),
])
