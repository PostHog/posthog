import clsx from 'clsx'
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
import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'

import { IconCursor, IconFlag, IconServer } from '@posthog/icons'

import {
    buildAutocaptureSeriesShortcuts,
    buildEventTypeFilterShortcuts,
} from 'lib/components/TaxonomicFilter/eventTypeShortcuts'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'
import {
    hasRecentContext,
    recentTaxonomicFiltersLogic,
    stripRecentContext,
} from 'lib/components/TaxonomicFilter/recentTaxonomicFiltersLogic'
import {
    hasPinnedContext,
    taxonomicFilterPinnedPropertiesLogic,
} from 'lib/components/TaxonomicFilter/taxonomicFilterPinnedPropertiesLogic'
import {
    DataWarehousePopoverField,
    ExcludedProperties,
    ListStorage,
    QuickFilterItem,
    SelectedProperties,
    SimpleOption,
    SkeletonItem,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
    isQuickFilterItem,
} from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconCohort } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, isString, objectsEqual, pluralize, toParams } from 'lib/utils'
import { getPromotedPropertyForEvent } from 'lib/utils/promotedEventProperty'
import {
    getEventDefinitionIcon,
    getEventMetadataDefinitionIcon,
    getPropertyDefinitionIcon,
    getRevenueAnalyticsDefinitionIcon,
} from 'scenes/data-management/events/DefinitionHeader'
import { dataWarehouseSettingsSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsSceneLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { COHORT_BEHAVIORAL_LIMITATIONS_URL } from 'scenes/feature-flags/constants'
import {
    getProductEventFilterOptions,
    getProductEventPropertyFilterOptions,
} from 'scenes/hog-functions/filters/HogFunctionFiltersInternal'
import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'
import { NotebookType } from 'scenes/notebooks/types'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { projectLogic } from 'scenes/projectLogic'
import { SavedFiltersTaxonomicGroup } from 'scenes/session-recordings/filters/SavedFiltersTaxonomicGroup'
import { teamLogic } from 'scenes/teamLogic'

import { actionsModel } from '~/models/actionsModel'
import { dashboardsModel } from '~/models/dashboardsModel'
import { groupsModel } from '~/models/groupsModel'
import { promotedEventPropertiesModel } from '~/models/promotedEventPropertiesModel'
import { propertyDefinitionsModel, updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { AnyDataNode, DatabaseSchemaField, DatabaseSchemaTable, NodeKind } from '~/queries/schema/schema-general'
import { getCoreFilterDefinition, getFilterLabel } from '~/taxonomy/helpers'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import {
    ActionType,
    CohortType,
    CoreFilterDefinition,
    DashboardType,
    EventDefinition,
    EventDefinitionType,
    Experiment,
    FeatureFlagType,
    Group,
    PersonProperty,
    PersonType,
    PropertyDefinition,
    PropertyDefinitionType,
    PropertyFilterType,
    QueryBasedInsightModel,
    SessionRecordingPlaylistType,
    TeamType,
} from '~/types'

import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'
import { HogFlowTaxonomicFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowTaxonomicFilters'

import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from '../PropertyFilters/utils'
import { InlineHogQLEditor } from './InlineHogQLEditor'
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

const TRAFFIC_TYPE_VIRTUAL_PROPERTIES = [
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

function keywordShortcutValue(item: QuickFilterItem): string {
    // Synthetic identity string used only as a React/selection key. Never parsed by consumers.
    return JSON.stringify({
        q: item.propertyKey,
        v: item.filterValue,
        e: item.eventName ?? null,
    })
}

type BaseGroupFns<T> = {
    getName: (instance: T) => string
    getValue: (instance: T) => TaxonomicFilterValue
    getIcon?: (instance: T) => JSX.Element
    getPopoverHeader: (instance: T) => string
}

/** Extend a group's presentation methods so they also handle `QuickFilterItem`s (keyword
 *  shortcuts), and attach a `keywordShortcuts` builder. `popoverHeader` lets each group label
 *  its own shortcut kind (e.g. "Autocapture shortcut" for series, "Event type shortcut" for
 *  property filters). */
function withKeywordShortcuts<T>(
    base: BaseGroupFns<T>,
    {
        popoverHeader,
        buildShortcuts,
    }: {
        popoverHeader: string
        buildShortcuts: (searchQuery: string) => QuickFilterItem[]
    }
): Pick<TaxonomicFilterGroup, 'getName' | 'getValue' | 'getIcon' | 'getPopoverHeader' | 'keywordShortcuts'> {
    const baseGetIcon = base.getIcon
    return {
        getName: (item: T | QuickFilterItem) => (isQuickFilterItem(item) ? item.name : base.getName(item)),
        getValue: (item: T | QuickFilterItem) =>
            isQuickFilterItem(item) ? keywordShortcutValue(item) : base.getValue(item),
        getIcon: baseGetIcon
            ? (item: T | QuickFilterItem) => (isQuickFilterItem(item) ? <IconCursor /> : baseGetIcon(item))
            : undefined,
        getPopoverHeader: (item: T | QuickFilterItem) =>
            isQuickFilterItem(item) ? popoverHeader : base.getPopoverHeader(item),
        keywordShortcuts: buildShortcuts,
    }
}

// Stable reference for CohortsWithAllUsers options to prevent cascading re-renders.
// taxonomicGroups has 14 dependencies that change during initial mount. Each change creates
// new group objects with inline options arrays, causing rawLocalItems → fuse → localItems →
// items → selectedItem reference changes. With CohortsWithAllUsers, selectedItemHasPopover
// returns true (getValue returns 'all'), so ControlledDefinitionPopover renders and its
// useEffect dispatches setDefinition on every selectedItem change, triggering kea store updates
// that combined with react-window's layout effect setState exceed React's 50-update limit.
const COHORTS_WITH_ALL_USERS_OPTIONS: CohortType[] = [{ id: 'all', name: 'All Users*' } as unknown as CohortType]

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
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            dataWarehouseSettingsSceneLogic, // This logic needs to be connected to stop the popover from erroring out
            ['dataWarehouseTables'],
            joinsLogic,
            ['columnsJoinedToPersons'],
            propertyDefinitionsModel,
            ['eventMetadataPropertyDefinitions'],
            featureFlagLogic,
            ['featureFlags'],
            promotedEventPropertiesModel,
            ['promotedProperties'],
        ],
        actions: [promotedEventPropertiesModel, ['ensureLoadedForEvents']],
    })),
    actions(() => ({
        moveUp: true,
        moveDown: true,
        selectSelected: true,
        enableMouseInteractions: true,
        tabLeft: true,
        tabRight: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
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
        // Combined selector that returns both event names and the distinct promoted properties
        // for those events. Combined into a single selector so taxonomicGroups stays under
        // kea's 16-dep tuple type limit; consumers destructure both fields.
        eventNamesWithPromotedProperties: [
            (s) => [s.eventNames, s.promotedProperties],
            (
                eventNames: string[],
                promotedProperties: Record<string, string>
            ): {
                eventNames: string[]
                promotedPropertiesForContextEvents: string[]
            } => {
                const distinct = new Set<string>()
                for (const eventName of eventNames) {
                    const promoted = getPromotedPropertyForEvent(eventName, promotedProperties)
                    if (promoted) {
                        distinct.add(promoted)
                    }
                }
                return {
                    eventNames,
                    promotedPropertiesForContextEvents: Array.from(distinct),
                }
            },
        ],
        schemaColumns: [() => [(_, props) => props.schemaColumns], (schemaColumns) => schemaColumns ?? []],
        maxContextOptions: [
            () => [(_, props) => props.maxContextOptions],
            (maxContextOptions) => maxContextOptions ?? [],
        ],
        dataWarehousePopoverFields: [
            () => [(_, props) => props.dataWarehousePopoverFields],
            (dataWarehousePopoverFields) => dataWarehousePopoverFields ?? [],
        ],
        suggestedFiltersLabel: [
            () => [(_, props) => props.suggestedFiltersLabel],
            (suggestedFiltersLabel) => suggestedFiltersLabel,
        ],
        metadataSource: [
            () => [(_, props) => props.metadataSource],
            (metadataSource): AnyDataNode =>
                metadataSource ?? { kind: NodeKind.HogQLQuery, query: 'select event from events' },
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
        hogQLExpressionComponentProps: [
            () => [(_, props) => props.hogQLGlobals, (_, props) => props.hogQLExpressionShowBreakdownLabelHint],
            (
                hogQLGlobals: Record<string, any> | undefined,
                showBreakdownLabelHint: boolean | undefined
            ): { globals?: Record<string, any>; showBreakdownLabelHint: boolean } => ({
                globals: hogQLGlobals,
                showBreakdownLabelHint: showBreakdownLabelHint ?? false,
            }),
        ],
        endpointFilters: [
            () => [(_, props) => props.endpointFilters],
            (endpointFilters: Record<string, any>) => endpointFilters,
        ],
        taxonomicGroups: [
            (s) => [
                s.currentTeam,
                s.currentProjectId,
                s.groupAnalyticsTaxonomicGroups,
                s.groupAnalyticsTaxonomicGroupNames,
                s.eventNamesWithPromotedProperties,
                s.schemaColumns,
                (_, props) => props.schemaColumnsLoading,
                s.metadataSource,
                s.suggestedFiltersLabel,
                s.propertyFilters,
                s.eventMetadataPropertyDefinitions,
                s.maxContextOptions,
                s.hideBehavioralCohorts,
                s.endpointFilters,
                s.hogQLExpressionComponentProps,
                s.featureFlags,
            ],
            (
                currentTeam: TeamType,
                projectId: number | null,
                groupAnalyticsTaxonomicGroups: TaxonomicFilterGroup[],
                groupAnalyticsTaxonomicGroupNames: TaxonomicFilterGroup[],
                eventNamesWithPromotedProperties: {
                    eventNames: string[]
                    promotedPropertiesForContextEvents: string[]
                },
                schemaColumns: DatabaseSchemaField[],
                schemaColumnsLoading: boolean | undefined,
                metadataSource: AnyDataNode,
                suggestedFiltersLabel: string | undefined,
                propertyFilters,
                eventMetadataPropertyDefinitions: PropertyDefinition[],
                maxContextOptions: MaxContextTaxonomicFilterOption[],
                hideBehavioralCohorts: boolean,
                endpointFilters: Record<string, any> | undefined,
                hogQLExpressionComponentProps: {
                    globals?: Record<string, any>
                    showBreakdownLabelHint: boolean
                },
                featureFlags: Record<string, boolean | string | undefined>
            ): TaxonomicFilterGroup[] => {
                const { eventNames, promotedPropertiesForContextEvents } = eventNamesWithPromotedProperties
                const { id: teamId } = currentTeam
                const { excludedProperties, propertyAllowList } = propertyFilters
                const groups: TaxonomicFilterGroup[] = [
                    {
                        name: 'Events',
                        searchPlaceholder: 'events',
                        type: TaxonomicFilterGroupType.Events,
                        options: [{ name: 'All events', value: null }].filter(
                            (o) => !excludedProperties[TaxonomicFilterGroupType.Events]?.includes(o.value)
                        ),
                        endpoint: combineUrl(`api/projects/${projectId}/event_definitions`, {
                            event_type: EventDefinitionType.Event,
                            exclude_hidden: true,
                        }).url,
                        excludedProperties:
                            excludedProperties?.[TaxonomicFilterGroupType.Events]?.filter(isString) ?? [],
                        ...withKeywordShortcuts<Record<string, any>>(
                            {
                                getName: (eventDefinition) => eventDefinition.name,
                                getValue: (eventDefinition) =>
                                    'id' in eventDefinition ? eventDefinition.name : eventDefinition.value,
                                getIcon: eventTaxonomicGroupProps.getIcon,
                                getPopoverHeader: eventTaxonomicGroupProps.getPopoverHeader,
                            },
                            {
                                popoverHeader: 'Autocapture shortcut',
                                buildShortcuts: buildAutocaptureSeriesShortcuts,
                            }
                        ),
                    },
                    {
                        name: 'Internal Events',
                        searchPlaceholder: 'internal events',
                        type: TaxonomicFilterGroupType.InternalEvents,
                        options: [
                            { name: 'All internal events', value: null },
                            ...getProductEventFilterOptions('activity-log').map((item) => ({
                                name: item.label,
                                value: item.value,
                            })),
                        ],
                        getName: (eventDefinition: Record<string, any>) => eventDefinition.name,
                        getValue: (eventDefinition: Record<string, any>) =>
                            'id' in eventDefinition ? eventDefinition.name : eventDefinition.value,
                        ...eventTaxonomicGroupProps,
                    },
                    {
                        name: 'Activity log properties',
                        searchPlaceholder: 'activity log properties',
                        type: TaxonomicFilterGroupType.ActivityLogProperties,
                        options: getProductEventPropertyFilterOptions('activity-log').map((value) => ({
                            name: value,
                            value,
                            group: TaxonomicFilterGroupType.EventProperties,
                        })),
                        getIcon: getPropertyDefinitionIcon,
                        getPopoverHeader: () => 'Activity log properties',
                    },
                    {
                        name: 'Workflow variables',
                        searchPlaceholder: 'variable key',
                        type: TaxonomicFilterGroupType.WorkflowVariables,
                        categoryLabel: () => 'Workflow variables',
                        render: HogFlowTaxonomicFilters,
                        getPopoverHeader: () => 'Workflow variables',
                    },
                    {
                        name: 'Actions',
                        searchPlaceholder: 'actions',
                        type: TaxonomicFilterGroupType.Actions,
                        logic: actionsModel,
                        value: 'actionsSorted',
                        getName: (action: ActionType) => action.name || '',
                        getValue: (action: ActionType) => action.id,
                        getPopoverHeader: () => 'Action',
                        getIcon: getEventDefinitionIcon,
                    },
                    {
                        name: 'Data warehouse tables',
                        searchPlaceholder: 'data warehouse tables',
                        type: TaxonomicFilterGroupType.DataWarehouse,
                        logic: dataWarehouseSettingsSceneLogic,
                        value: 'dataWarehouseTablesAndViews',
                        valueLoading: 'databaseLoading',
                        getName: (table: DatabaseSchemaTable) => table.name,
                        getValue: (table: DatabaseSchemaTable) => table.name,
                        getPopoverHeader: () => 'Data Warehouse Table',
                        getIcon: () => <IconServer />,
                    },
                    ...(schemaColumns.length > 0 || schemaColumnsLoading
                        ? [
                              {
                                  name: 'Data warehouse properties',
                                  searchPlaceholder: 'data warehouse properties',
                                  type: TaxonomicFilterGroupType.DataWarehouseProperties,
                                  options: schemaColumns,
                                  getName: (col: DatabaseSchemaField) => col.name,
                                  getValue: (col: DatabaseSchemaField) => col.name,
                                  getPopoverHeader: () => 'Data Warehouse Column',
                                  getIcon: () => <IconServer />,
                              },
                          ]
                        : []),
                    {
                        name: 'Extended person properties',
                        searchPlaceholder: 'extended person properties',
                        type: TaxonomicFilterGroupType.DataWarehousePersonProperties,
                        logic: joinsLogic,
                        value: 'columnsJoinedToPersons',
                        getName: (personProperty: PersonProperty) => personProperty.name,
                        getValue: (personProperty: PersonProperty) => personProperty.id,
                        getPopoverHeader: () => 'Extended Person Property',
                    },
                    {
                        name: 'Autocapture elements',
                        searchPlaceholder: 'autocapture elements',
                        type: TaxonomicFilterGroupType.Elements,
                        options: ['tag_name', 'text', 'href', 'selector'].map((option) => ({
                            name: option,
                        })) as SimpleOption[],
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => 'Autocapture Element',
                    },
                    {
                        name: 'Metadata',
                        searchPlaceholder: 'metadata',
                        type: TaxonomicFilterGroupType.Metadata,
                        // populate options using `optionsFromProp` depending on context in which
                        // this taxonomic group type is used
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        ...propertyTaxonomicGroupProps(CORE_FILTER_DEFINITIONS_BY_GROUP.metadata),
                    },
                    {
                        name: 'Event properties',
                        searchPlaceholder: 'event properties',
                        type: TaxonomicFilterGroupType.EventProperties,
                        endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
                            is_feature_flag: false,
                            ...(eventNames.length > 0 ? { event_names: eventNames } : {}),
                            properties: propertyAllowList?.[TaxonomicFilterGroupType.EventProperties]
                                ? propertyAllowList[TaxonomicFilterGroupType.EventProperties].join(',')
                                : undefined,
                            exclude_hidden: true,
                        }).url,
                        scopedEndpoint:
                            eventNames.length > 0
                                ? combineUrl(`api/projects/${projectId}/property_definitions`, {
                                      event_names: eventNames,
                                      is_feature_flag: false,
                                      filter_by_event_names: true,
                                      properties: propertyAllowList?.[TaxonomicFilterGroupType.EventProperties]
                                          ? propertyAllowList[TaxonomicFilterGroupType.EventProperties].join(',')
                                          : undefined,
                                      exclude_hidden: true,
                                  }).url
                                : undefined,
                        expandLabel: ({ count, expandedCount }: { count: number; expandedCount: number }) =>
                            `Show ${pluralize(expandedCount - count, 'property', 'properties')} that ${pluralize(
                                expandedCount - count,
                                'has',
                                'have',
                                false
                            )}n't been seen with ${pluralize(eventNames.length, 'this event', 'these events', false)}`,
                        excludedProperties: [
                            ...(excludedProperties?.[TaxonomicFilterGroupType.EventProperties]?.filter(isString) ?? []),
                            ...(!featureFlags[FEATURE_FLAGS.TRAFFIC_TYPE_VIRTUAL_PROPERTIES]
                                ? TRAFFIC_TYPE_VIRTUAL_PROPERTIES
                                : []),
                        ],
                        propertyAllowList:
                            propertyAllowList?.[TaxonomicFilterGroupType.EventProperties]?.filter(isString),
                        ...withKeywordShortcuts<PropertyDefinition>(
                            {
                                getName: (propertyDefinition) => propertyDefinition.name,
                                getValue: (propertyDefinition) => propertyDefinition.name,
                                ...propertyTaxonomicGroupProps(),
                            },
                            {
                                popoverHeader: 'Event type shortcut',
                                buildShortcuts: buildEventTypeFilterShortcuts,
                            }
                        ),
                    },
                    {
                        name: 'Internal event properties',
                        searchPlaceholder: 'internal event properties',
                        type: TaxonomicFilterGroupType.InternalEventProperties,
                        options: getProductEventPropertyFilterOptions('activity-log').map((value) => ({
                            name: value,
                            value,
                            group: TaxonomicFilterGroupType.EventProperties,
                        })),
                        getIcon: getPropertyDefinitionIcon,
                        getPopoverHeader: () => 'Internal event properties',
                    },
                    {
                        name: 'Event metadata',
                        searchPlaceholder: 'event metadata',
                        type: TaxonomicFilterGroupType.EventMetadata,
                        options: eventMetadataPropertyDefinitions,
                        getIcon: (option: PropertyDefinition) => getEventMetadataDefinitionIcon(option),
                        getName: (option: PropertyDefinition) => {
                            const coreDefinition = getCoreFilterDefinition(
                                option.id,
                                TaxonomicFilterGroupType.EventMetadata
                            )
                            return coreDefinition ? coreDefinition.label : option.name
                        },
                        getValue: (option: PropertyDefinition) => option.id,
                        valuesEndpoint: (key) => {
                            return `api/event/values/?key=${encodeURIComponent(key)}&is_column=true`
                        },
                        getPopoverHeader: () => 'Event metadata',
                    },
                    {
                        name: 'Feature flags',
                        searchPlaceholder: 'feature flags',
                        type: TaxonomicFilterGroupType.EventFeatureFlags,
                        endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
                            is_feature_flag: true,
                            ...(eventNames.length > 0 ? { event_names: eventNames } : {}),
                        }).url,
                        scopedEndpoint:
                            eventNames.length > 0
                                ? combineUrl(`api/projects/${projectId}/property_definitions`, {
                                      event_names: eventNames,
                                      is_feature_flag: true,
                                      filter_by_event_names: true,
                                  }).url
                                : undefined,
                        expandLabel: ({ count, expandedCount }: { count: number; expandedCount: number }) =>
                            `Show ${pluralize(expandedCount - count, 'property', 'properties')} that ${pluralize(
                                expandedCount - count,
                                'has',
                                'have',
                                false
                            )}n't been seen with ${pluralize(eventNames.length, 'this event', 'these events', false)}`,
                        getName: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                        getValue: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                        excludedProperties:
                            excludedProperties?.[TaxonomicFilterGroupType.EventFeatureFlags]?.filter(isString),
                        ...propertyTaxonomicGroupProps(),
                    },
                    {
                        name: 'Issues',
                        searchPlaceholder: 'issues',
                        type: TaxonomicFilterGroupType.ErrorTrackingIssues,
                        options: Object.entries(
                            CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.ErrorTrackingIssues]
                        )
                            .map(([key, { label }]) => ({
                                value: key,
                                name: label,
                            }))
                            .filter(
                                (o) =>
                                    !excludedProperties[TaxonomicFilterGroupType.ErrorTrackingIssues]?.includes(o.value)
                            ),
                        getName: (option) => option.name,
                        getValue: (option) => option.value,
                        valuesEndpoint: (key) =>
                            `api/environments/${projectId}/error_tracking/issues/values?key=` + key,
                        getPopoverHeader: () => 'Issues',
                    },
                    {
                        name: 'Exception properties',
                        searchPlaceholder: 'exceptions',
                        type: TaxonomicFilterGroupType.ErrorTrackingProperties,
                        options: [
                            ...getProductEventPropertyFilterOptions('error-tracking').map((value) => ({
                                name: value,
                                value,
                                group: TaxonomicFilterGroupType.EventProperties,
                            })),
                            ...(currentTeam?.person_display_name_properties
                                ? currentTeam.person_display_name_properties.map((property) => ({
                                      name: property,
                                      value: property,
                                      group: TaxonomicFilterGroupType.PersonProperties,
                                  }))
                                : []),
                        ],
                        getIcon: getPropertyDefinitionIcon,
                        getPopoverHeader: () => 'Exception properties',
                    },
                    {
                        name: 'Revenue analytics properties',
                        searchPlaceholder: 'revenue analytics properties',
                        type: TaxonomicFilterGroupType.RevenueAnalyticsProperties,
                        options: Object.entries(
                            CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.RevenueAnalyticsProperties]
                        )
                            .map(([key, { type: property_type }]) => ({
                                id: key,
                                name: key,
                                value: key,
                                property_type,
                                type: PropertyDefinitionType.RevenueAnalytics,
                            }))
                            .filter(
                                (o) =>
                                    !excludedProperties[TaxonomicFilterGroupType.RevenueAnalyticsProperties]?.includes(
                                        o.value
                                    )
                            ),
                        getIcon: (option: PropertyDefinition): JSX.Element => getRevenueAnalyticsDefinitionIcon(option),
                        getName: (option: PropertyDefinition) => {
                            const coreDefinition = getCoreFilterDefinition(
                                option.id,
                                TaxonomicFilterGroupType.RevenueAnalyticsProperties
                            )

                            return coreDefinition ? coreDefinition.label : option.name
                        },
                        getValue: (option: PropertyDefinition) => option.id,
                        valuesEndpoint: (key) => {
                            return `api/environments/${projectId}/revenue_analytics/taxonomy/values?key=${encodeURIComponent(
                                key
                            )}`
                        },
                        getPopoverHeader: () => 'Revenue analytics properties',
                    },
                    {
                        name: 'Logs',
                        searchPlaceholder: 'logs',
                        type: TaxonomicFilterGroupType.Logs,
                        options: [{ key: 'message', name: 'Message', propertyFilterType: 'log' }],
                        localItemsSearch: (items: any[], q: string): any[] => {
                            if (!q) {
                                return items
                            }
                            return [
                                {
                                    key: 'message',
                                    name: 'Search log message for "' + q + '"',
                                    value: q,
                                    propertyFilterType: 'log',
                                },
                            ].concat(items.filter((item) => item.name?.toLowerCase().includes(q.toLowerCase())))
                        },
                        getName: (option: { key: string; name: string }) => option.name,
                        getValue: (option: { key: string; name: string }) => option.key,
                        getPopoverHeader: () => 'Log attributes',
                    },
                    {
                        name: 'Log attributes',
                        searchPlaceholder: 'attributes',
                        type: TaxonomicFilterGroupType.LogAttributes,
                        endpoint: combineUrl(`api/environments/${projectId}/logs/attributes`, {
                            attribute_type: 'log',
                            search_values: 'true',
                            ...endpointFilters,
                        }).url,
                        valuesEndpoint: (key) =>
                            combineUrl(`api/environments/${projectId}/logs/values`, {
                                attribute_type: 'log',
                                key: key,
                                ...endpointFilters,
                            }).url,
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => 'Log attributes',
                    },
                    {
                        name: 'Resource attributes',
                        searchPlaceholder: 'resources',
                        type: TaxonomicFilterGroupType.LogResourceAttributes,
                        endpoint: combineUrl(`api/environments/${projectId}/logs/attributes`, {
                            attribute_type: 'resource',
                            search_values: 'true',
                            ...endpointFilters,
                        }).url,
                        valuesEndpoint: (key) =>
                            combineUrl(`api/environments/${projectId}/logs/values`, {
                                attribute_type: 'resource',
                                key: key,
                                ...endpointFilters,
                            }).url,
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => 'Resource attributes',
                    },
                    {
                        name: 'Spans',
                        searchPlaceholder: 'spans',
                        type: TaxonomicFilterGroupType.Spans,
                        options: [
                            { key: 'name', name: 'name', propertyFilterType: 'span' },
                            { key: 'kind', name: 'kind', propertyFilterType: 'span' },
                            { key: 'duration', name: 'duration (ms)', propertyFilterType: 'span' },
                            { key: 'trace_id', name: 'trace_id', propertyFilterType: 'span' },
                            { key: 'span_id', name: 'span_id', propertyFilterType: 'span' },
                            { key: 'status_code', name: 'status code', propertyFilterType: 'span' },
                        ],
                        valuesEndpoint: (key) =>
                            key === 'name'
                                ? combineUrl(`api/environments/${projectId}/tracing/spans/values`, {
                                      attribute_type: 'span',
                                      key: key,
                                      ...endpointFilters,
                                  }).url
                                : undefined,
                        localItemsSearch: (items: any[], q: string): any[] => {
                            if (!q) {
                                return items
                            }
                            return [
                                {
                                    key: 'message',
                                    name: 'Search span message for "' + q + '"',
                                    value: q,
                                    propertyFilterType: 'span',
                                },
                            ].concat(items.filter((item) => item.name?.toLowerCase().includes(q.toLowerCase())))
                        },
                        getName: (option: { key: string; name: string }) => option.name,
                        getValue: (option: { key: string; name: string }) => option.key,
                        getPopoverHeader: () => 'Span attributes',
                    },
                    {
                        name: 'Span attributes',
                        searchPlaceholder: 'span attributes',
                        type: TaxonomicFilterGroupType.SpanAttributes,
                        endpoint: combineUrl(`api/environments/${projectId}/tracing/spans/attributes`, {
                            attribute_type: 'span',
                            ...endpointFilters,
                        }).url,
                        valuesEndpoint: (key) =>
                            combineUrl(`api/environments/${projectId}/tracing/spans/values`, {
                                attribute_type: 'span',
                                key: key,
                                ...endpointFilters,
                            }).url,
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => 'Span attributes',
                    },
                    {
                        name: 'Span resource attributes',
                        searchPlaceholder: 'span resources',
                        type: TaxonomicFilterGroupType.SpanResourceAttributes,
                        endpoint: combineUrl(`api/environments/${projectId}/tracing/spans/attributes`, {
                            attribute_type: 'resource',
                            ...endpointFilters,
                        }).url,
                        valuesEndpoint: (key) =>
                            combineUrl(`api/environments/${projectId}/tracing/spans/values`, {
                                attribute_type: 'resource',
                                key: key,
                                ...endpointFilters,
                            }).url,
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => 'Span resource attributes',
                    },
                    {
                        name: 'Numerical event properties',
                        searchPlaceholder: 'numerical event properties',
                        type: TaxonomicFilterGroupType.NumericalEventProperties,
                        endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
                            is_numerical: true,
                            event_names: eventNames,
                        }).url,
                        getName: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                        getValue: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                        ...propertyTaxonomicGroupProps(),
                    },
                    {
                        name: 'Person properties',
                        searchPlaceholder: 'person properties',
                        type: TaxonomicFilterGroupType.PersonProperties,
                        endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
                            type: 'person',
                            properties: propertyAllowList?.[TaxonomicFilterGroupType.PersonProperties]
                                ? propertyAllowList[TaxonomicFilterGroupType.PersonProperties].join(',')
                                : undefined,
                            exclude_hidden: true,
                        }).url,
                        getName: (personProperty: PersonProperty) => personProperty.name,
                        getValue: (personProperty: PersonProperty) => personProperty.name,
                        propertyAllowList:
                            propertyAllowList?.[TaxonomicFilterGroupType.PersonProperties]?.filter(isString),
                        ...propertyTaxonomicGroupProps(CORE_FILTER_DEFINITIONS_BY_GROUP.person_properties),
                    },
                    {
                        name: 'Cohorts',
                        searchPlaceholder: 'cohorts',
                        type: TaxonomicFilterGroupType.Cohorts,
                        endpoint: combineUrl(`api/projects/${projectId}/cohorts/`).url,
                        value: 'cohorts',
                        getName: (cohort: CohortType) => cohort.name || `Cohort ${cohort.id}`,
                        getValue: (cohort: CohortType) => cohort.id,
                        getPopoverHeader: (cohort: CohortType) => `${cohort.is_static ? 'Static' : 'Dynamic'} Cohort`,
                        getIcon: function _getIcon(): JSX.Element {
                            return <IconCohort className="taxonomy-icon taxonomy-icon-muted" />
                        },
                        footerMessage: hideBehavioralCohorts ? (
                            <>
                                <Link to={COHORT_BEHAVIORAL_LIMITATIONS_URL} target="_blank">
                                    Some cohorts excluded due to containing behavioral filters.
                                </Link>
                            </>
                        ) : undefined,
                    },
                    {
                        name: 'Cohorts',
                        searchPlaceholder: 'cohorts',
                        type: TaxonomicFilterGroupType.CohortsWithAllUsers,
                        endpoint: combineUrl(`api/projects/${projectId}/cohorts/`).url,
                        options: COHORTS_WITH_ALL_USERS_OPTIONS,
                        getName: (cohort: CohortType) => cohort.name || `Cohort ${cohort.id}`,
                        getValue: (cohort: CohortType) => cohort.id,
                        getPopoverHeader: () => `All Users`,
                        getIcon: function _getIcon(): JSX.Element {
                            return <IconCohort className="taxonomy-icon taxonomy-icon-muted" />
                        },
                    },
                    // PageviewUrls returns a URL string value, used in paths and property filters.
                    // PageviewEvents creates a $pageview event with $current_url property filter,
                    // used in trends and funnels series pickers.
                    {
                        name: 'Pageview URLs',
                        searchPlaceholder: 'pageview URLs',
                        type: TaxonomicFilterGroupType.PageviewUrls,
                        endpoint: `api/environments/${teamId}/events/values/?key=$current_url&event_name=$pageview`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Pageview URL`,
                        minSearchQueryLength: 3,
                        searchDescription: 'URLs seen on pageview events',
                    },
                    {
                        name: 'Pageview events',
                        searchPlaceholder: 'pageview events',
                        type: TaxonomicFilterGroupType.PageviewEvents,
                        endpoint: `api/environments/${teamId}/events/values/?key=$current_url&event_name=$pageview`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Pageview event`,
                        minSearchQueryLength: 3,
                        searchDescription: 'pageview events filtered by URL',
                    },
                    // Screens returns a screen name value, used in paths and property filters.
                    // ScreenEvents creates a $screen event with $screen_name property filter,
                    // used in trends and funnels series pickers.
                    {
                        name: 'Screens',
                        searchPlaceholder: 'screens',
                        type: TaxonomicFilterGroupType.Screens,
                        endpoint: `api/environments/${teamId}/events/values/?key=$screen_name&event_name=$screen`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Screen`,
                        minSearchQueryLength: 3,
                        searchDescription: 'screen names seen on screen events',
                    },
                    {
                        name: 'Screen events',
                        searchPlaceholder: 'screen events',
                        type: TaxonomicFilterGroupType.ScreenEvents,
                        endpoint: `api/environments/${teamId}/events/values/?key=$screen_name&event_name=$screen`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Screen event`,
                        minSearchQueryLength: 3,
                        searchDescription: 'screen events filtered by screen name',
                    },
                    {
                        name: 'Email addresses',
                        searchPlaceholder: 'email addresses',
                        type: TaxonomicFilterGroupType.EmailAddresses,
                        endpoint: `api/environments/${teamId}/persons/values/?key=email`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Email address`,
                        minSearchQueryLength: 5,
                        searchDescription: 'email addresses seen in person properties',
                    },
                    {
                        name: 'Autocapture events',
                        searchPlaceholder: 'autocapture events',
                        type: TaxonomicFilterGroupType.AutocaptureEvents,
                        endpoint: `api/environments/${teamId}/events/values/?key=$el_text&event_name=$autocapture`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Autocapture event`,
                        minSearchQueryLength: 3,
                        searchDescription: 'element text seen on autocapture events',
                    },
                    {
                        name: 'Custom Events',
                        searchPlaceholder: 'custom events',
                        type: TaxonomicFilterGroupType.CustomEvents,
                        endpoint: combineUrl(`api/projects/${projectId}/event_definitions`, {
                            event_type: EventDefinitionType.EventCustom,
                            exclude_hidden: true,
                        }).url,
                        getName: (eventDefinition: EventDefinition) => eventDefinition.name,
                        getValue: (eventDefinition: EventDefinition) => eventDefinition.name,
                        ...eventTaxonomicGroupProps,
                    },
                    {
                        name: 'Wildcards',
                        searchPlaceholder: 'wildcards',
                        type: TaxonomicFilterGroupType.Wildcards,
                        // Populated via optionsFromProp
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Wildcard`,
                    },
                    {
                        name: 'Persons',
                        searchPlaceholder: 'persons',
                        type: TaxonomicFilterGroupType.Persons,
                        endpoint: `api/environments/${teamId}/persons/`,
                        getName: (person: PersonType) => person.name || 'Anon user?',
                        getValue: (person: PersonType) => person.distinct_ids[0],
                        getPopoverHeader: () => `Person`,
                    },
                    {
                        name: 'Insights',
                        searchPlaceholder: 'insights',
                        type: TaxonomicFilterGroupType.Insights,
                        endpoint: combineUrl(`api/environments/${teamId}/insights/`, {
                            saved: true,
                        }).url,
                        getName: (insight: QueryBasedInsightModel) => insight.name,
                        getValue: (insight: QueryBasedInsightModel) => insight.short_id,
                        getPopoverHeader: () => `Insights`,
                    },
                    {
                        name: 'Feature Flags',
                        searchPlaceholder: 'feature flags',
                        type: TaxonomicFilterGroupType.FeatureFlags, // Feature flag dependencies
                        endpoint: combineUrl(`api/projects/${projectId}/feature_flags/`).url,
                        getName: (featureFlag: FeatureFlagType) => {
                            const name = featureFlag.key || featureFlag.name
                            const isInactive = !featureFlag.active
                            return isInactive ? `${name} (disabled)` : name
                        },
                        getValue: (featureFlag: FeatureFlagType) => featureFlag.id || '',
                        getPopoverHeader: () => `Feature Flags`,
                        getIcon: (featureFlag: FeatureFlagType) => (
                            <IconFlag className={clsx('size-4', !featureFlag.active && 'text-muted-alt opacity-50')} />
                        ),
                        getIsDisabled: (featureFlag: FeatureFlagType) => !featureFlag.active,
                        localItemsSearch: (
                            items: TaxonomicDefinitionTypes[],
                            query: string
                        ): TaxonomicDefinitionTypes[] => {
                            // Note: This function doesn't have direct access to the current value
                            // The actual filtering logic needs to be implemented in the infinite list logic
                            // For now, just handle search filtering
                            if (!query) {
                                return items
                            }

                            return items.filter((item: TaxonomicDefinitionTypes) => {
                                // Type guard for FeatureFlagType
                                if ('key' in item && 'name' in item) {
                                    const flag = item as unknown as FeatureFlagType
                                    return (flag.key || flag.name || '').toLowerCase().includes(query.toLowerCase())
                                }
                                // For other types, check if they have a name property
                                if ('name' in item) {
                                    return (item.name || '').toLowerCase().includes(query.toLowerCase())
                                }
                                return true
                            })
                        },
                        excludedProperties:
                            excludedProperties?.[TaxonomicFilterGroupType.FeatureFlags]?.filter(isString),
                    },
                    {
                        name: 'Experiments',
                        searchPlaceholder: 'experiments',
                        type: TaxonomicFilterGroupType.Experiments,
                        logic: experimentsLogic,
                        value: 'experiments',
                        getName: (experiment: Experiment) => experiment.name,
                        getValue: (experiment: Experiment) => experiment.id,
                        getPopoverHeader: () => `Experiments`,
                    },
                    {
                        name: 'Dashboards',
                        searchPlaceholder: 'dashboards',
                        type: TaxonomicFilterGroupType.Dashboards,
                        logic: dashboardsModel,
                        value: 'nameSortedDashboards',
                        getName: (dashboard: DashboardType) => dashboard.name,
                        getValue: (dashboard: DashboardType) => dashboard.id,
                        getPopoverHeader: () => `Dashboards`,
                    },
                    {
                        name: 'Notebooks',
                        searchPlaceholder: 'notebooks',
                        type: TaxonomicFilterGroupType.Notebooks,
                        value: 'notebooks',
                        endpoint: `api/projects/${projectId}/notebooks/`,
                        getName: (notebook: NotebookType) => notebook.title || `Notebook ${notebook.short_id}`,
                        getValue: (notebook: NotebookType) => notebook.short_id,
                        getPopoverHeader: () => 'Notebooks',
                    },
                    {
                        name: 'Session properties',
                        searchPlaceholder: 'sessions',
                        type: TaxonomicFilterGroupType.SessionProperties,
                        ...(propertyAllowList
                            ? {
                                  options: propertyAllowList[TaxonomicFilterGroupType.SessionProperties]
                                      ?.filter(isString)
                                      ?.map((property: string) => ({
                                          name: property,
                                          value: property,
                                      })),
                              }
                            : {
                                  endpoint: `api/environments/${teamId}/sessions/property_definitions`,
                              }),
                        getName: (option: any) => option.name,
                        getValue: (option) => option.name,
                        getPopoverHeader: () => 'Session',
                        getIcon: getPropertyDefinitionIcon,
                    },
                    {
                        name: 'SQL expression',
                        searchPlaceholder: null,
                        categoryLabel: () => 'SQL expression',
                        type: TaxonomicFilterGroupType.HogQLExpression,
                        render: InlineHogQLEditor,
                        getPopoverHeader: () => 'SQL expression',
                        componentProps: { metadataSource, ...hogQLExpressionComponentProps },
                    },
                    {
                        name: 'Replay',
                        searchPlaceholder: 'Replay',
                        type: TaxonomicFilterGroupType.Replay,
                        options: [
                            {
                                key: 'visited_page',
                                name: getFilterLabel('visited_page', TaxonomicFilterGroupType.Replay),
                                propertyFilterType: PropertyFilterType.Recording,
                            },
                            {
                                key: 'snapshot_source',
                                name: getFilterLabel('snapshot_source', TaxonomicFilterGroupType.Replay),
                                propertyFilterType: PropertyFilterType.Recording,
                            },
                            {
                                key: 'level',
                                name: getFilterLabel('level', TaxonomicFilterGroupType.LogEntries),
                                propertyFilterType: PropertyFilterType.LogEntry,
                            },
                            {
                                key: 'message',
                                name: getFilterLabel('message', TaxonomicFilterGroupType.LogEntries),
                                propertyFilterType: PropertyFilterType.LogEntry,
                            },
                            {
                                key: 'comment_text',
                                name: getFilterLabel('comment_text', TaxonomicFilterGroupType.Replay),
                                propertyFilterType: PropertyFilterType.Recording,
                            },
                        ],
                        getName: (option: Record<string, any>) => option.name,
                        getValue: (option: Record<string, any>) => option.key,
                        valuesEndpoint: (key) => {
                            if (key === 'visited_page') {
                                return (
                                    `api/environments/${teamId}/events/values/?key=` +
                                    encodeURIComponent('$current_url') +
                                    '&event_name=' +
                                    encodeURIComponent('$pageview')
                                )
                            }
                        },
                        getPopoverHeader: () => 'Replay',
                    },
                    {
                        name: 'Saved filters',
                        searchPlaceholder: 'saved filters',
                        type: TaxonomicFilterGroupType.ReplaySavedFilters,
                        endpoint: combineUrl(`api/projects/${projectId}/session_recording_playlists/`, {
                            type: 'filters',
                            order: '-last_modified_at',
                        }).url,
                        render: SavedFiltersTaxonomicGroup,
                        getName: (filter: SessionRecordingPlaylistType) =>
                            filter.name || filter.derived_name || 'Unnamed',
                        getValue: (filter: SessionRecordingPlaylistType) => filter.short_id,
                        getPopoverHeader: () => 'Saved filter',
                    },
                    {
                        name: 'On this page',
                        searchPlaceholder: 'elements from this page',
                        type: TaxonomicFilterGroupType.MaxAIContext,
                        options: maxContextOptions,
                        getName: (option: MaxContextTaxonomicFilterOption) => option.name,
                        getValue: (option: MaxContextTaxonomicFilterOption) => option.value,
                        getIcon: (option: MaxContextTaxonomicFilterOption) => {
                            const IconComponent = option.icon
                            return <IconComponent />
                        },
                        getPopoverHeader: () => 'On this page',
                    },
                    {
                        name: suggestedFiltersLabel ?? 'Suggested filters',
                        searchPlaceholder: (suggestedFiltersLabel ?? 'Suggested filters').toLowerCase(),
                        categoryLabel: (count: number) =>
                            (suggestedFiltersLabel ?? 'Suggested filters') + (count > 0 ? `: ${count}` : ''),
                        type: TaxonomicFilterGroupType.SuggestedFilters,
                        isLocalOnly: true,
                        isMetaGroup: true,
                        options: [
                            // Promoted properties for any event in context come first — if a team
                            // has marked a property as the one that summarises this event, it's
                            // the property they almost certainly want to filter or break down by.
                            ...promotedPropertiesForContextEvents.map((name) => ({
                                name,
                                group: TaxonomicFilterGroupType.EventProperties,
                            })),
                            ...(eventNames.includes('$autocapture')
                                ? (['text', 'selector'] as const).map((name) => ({
                                      name,
                                      group: TaxonomicFilterGroupType.Elements,
                                  }))
                                : []),
                        ],
                        getName: (item: TaxonomicDefinitionTypes) => ('name' in item ? item.name : '') || '',
                        getValue: (item: TaxonomicDefinitionTypes): TaxonomicFilterValue =>
                            'name' in item ? (item.name ?? null) : null,
                        getPopoverHeader: () => suggestedFiltersLabel ?? 'Suggested filters',
                    },
                    {
                        name: 'Recent',
                        searchPlaceholder: 'recent',
                        type: TaxonomicFilterGroupType.RecentFilters,
                        isLocalOnly: true,
                        isMetaGroup: true,
                        logic: recentTaxonomicFiltersLogic,
                        value: 'recentFilterItems',
                        getName: (item: TaxonomicDefinitionTypes) => ('name' in item ? item.name : '') || '',
                        getValue: (item: TaxonomicDefinitionTypes): TaxonomicFilterValue =>
                            'name' in item ? (item.name ?? null) : null,
                        getPopoverHeader: () => 'Recent',
                    } as TaxonomicFilterGroup,
                    {
                        name: 'Pinned',
                        searchPlaceholder: 'pinned',
                        type: TaxonomicFilterGroupType.PinnedFilters,
                        isLocalOnly: true,
                        isMetaGroup: true,
                        logic: taxonomicFilterPinnedPropertiesLogic,
                        value: 'pinnedFilterItems',
                        getName: (item: TaxonomicDefinitionTypes) => ('name' in item ? item.name : '') || '',
                        getValue: (item: TaxonomicDefinitionTypes): TaxonomicFilterValue =>
                            'name' in item ? (item.name ?? null) : null,
                        getPopoverHeader: () => 'Pinned',
                    } as TaxonomicFilterGroup,
                    ...groupAnalyticsTaxonomicGroups,
                    ...groupAnalyticsTaxonomicGroupNames,
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
        groupAnalyticsTaxonomicGroupNames: [
            (s) => [s.groupTypes, s.currentTeamId, s.aggregationLabel],
            (groupTypes, teamId, aggregationLabel): TaxonomicFilterGroup[] =>
                Array.from(groupTypes.values()).map((type) => ({
                    name: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).plural)}`,
                    searchPlaceholder: `${aggregationLabel(type.group_type_index).plural}`,
                    type: `${TaxonomicFilterGroupType.GroupNamesPrefix}_${type.group_type_index}` as unknown as TaxonomicFilterGroupType,
                    endpoint: combineUrl(`api/environments/${teamId}/groups/`, {
                        group_type_index: type.group_type_index,
                    }).url,
                    getPopoverHeader: () => `Group Names`,
                    getName: (group: Group) => groupDisplayId(group.group_key, group.group_properties),
                    getValue: (group: Group) => group.group_key,
                    groupTypeIndex: type.group_type_index,
                })),
        ],
        groupAnalyticsTaxonomicGroups: [
            (s) => [s.groupTypes, s.currentProjectId, s.aggregationLabel],
            (groupTypes, projectId, aggregationLabel): TaxonomicFilterGroup[] =>
                Array.from(groupTypes.values()).map((type) => ({
                    name: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).singular)} properties`,
                    searchPlaceholder: `${aggregationLabel(type.group_type_index).singular} properties`,
                    type: `${TaxonomicFilterGroupType.GroupsPrefix}_${type.group_type_index}` as unknown as TaxonomicFilterGroupType,
                    endpoint: combineUrl(`api/projects/${projectId}/property_definitions`, {
                        type: 'group',
                        group_type_index: type.group_type_index,
                        exclude_hidden: true,
                    }).url,
                    valuesEndpoint: (key) =>
                        `api/projects/${projectId}/groups/property_values?${toParams({
                            key,
                            group_type_index: type.group_type_index,
                        })}`,
                    getName: (group) => group.name,
                    getValue: (group) => group.name,
                    getPopoverHeader: () => `Property`,
                    getIcon: getPropertyDefinitionIcon,
                    groupTypeIndex: type.group_type_index,
                })),
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
            ],
            (
                redistributed: TopMatchItem[],
                taxonomicGroupTypes: TaxonomicFilterGroupType[],
                loadingGroupTypes: TaxonomicFilterGroupType[],
                taxonomicGroups: TaxonomicFilterGroup[],
                searchQuery: string,
                metaGroupTypes: Set<string>
            ): (TopMatchItem | SkeletonItem)[] => {
                if (!searchQuery) {
                    return redistributed
                }

                const nonMetaGroups = taxonomicGroupTypes.filter((t) => !metaGroupTypes.has(t))

                const result: (TopMatchItem | SkeletonItem)[] = []
                for (const groupType of nonMetaGroups) {
                    const groupItems = redistributed.filter((item) => item.group === groupType)
                    if (groupItems.length > 0) {
                        result.push(...groupItems)
                    } else if (loadingGroupTypes.includes(groupType)) {
                        const groupDef = taxonomicGroups.find((g) => g.type === groupType)
                        const groupName = groupDef?.name ?? groupType
                        for (let i = 0; i < SKELETON_ROWS_PER_GROUP; i++) {
                            result.push({ _skeleton: true, group: groupType, groupName })
                        }
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
    }),
    beforeUnmount(({ values, cache }) => {
        posthog.capture('taxonomic filter closed', {
            dwellMs: Date.now() - (cache.openedAt ?? Date.now()),
            hadSelection: !!cache.hadSelection,
            groupType: values.activeTab,
        })
    }),
    propsChanged(({ actions, props }, oldProps) => {
        // When the in-context events change (e.g. an insight series swaps event), ask the model
        // to load any team-configured promoted properties for those names.
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

                posthog.capture('taxonomic filter item selected', {
                    groupType: values.activeTab,
                    sourceGroupType,
                    wasFromPinnedList,
                    wasFromRecents,
                    wasQuickFilter,
                    hadSearchInput,
                    position: meta?.position,
                    query: values.searchQuery || undefined,
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
                // Skip property groups — these are just the key-picking step;
                // the complete filter (with operator + value) is recorded by propertyFilterLogic.
                // Skip QuickFilterItem shortcuts — they are synthetic, not real data definitions.
                const hasCompletePropertyFilter = hasRecentContext(item) && item._recentContext.propertyFilter
                const isRecordedByPropertyFilterLogic =
                    !hasCompletePropertyFilter &&
                    (PROPERTY_TAXONOMIC_GROUP_TYPES.has(sourceGroupType) ||
                        SHORTCUT_TO_PROPERTY_FILTER_GROUP_TYPES.has(sourceGroupType) ||
                        sourceGroupType.startsWith(TaxonomicFilterGroupType.GroupsPrefix))

                if (!isRecordedByPropertyFilterLogic && !isQuickFilterItem(item)) {
                    setTimeout(() => {
                        if (recentTaxonomicFiltersLogic.isMounted()) {
                            const stripped = hasRecentContext(item) ? stripRecentContext(item) : item
                            const cleanItem = { name: stripped.name, ...(stripped.id ? { id: stripped.id } : {}) }
                            const sourceGroupName = hasRecentContext(item)
                                ? item._recentContext.sourceGroupName
                                : group.name
                            const propertyFilterFromRecent = hasRecentContext(item)
                                ? item._recentContext.propertyFilter
                                : undefined
                            recentTaxonomicFiltersLogic.actions.recordRecentFilter(
                                sourceGroupType,
                                sourceGroupName,
                                value,
                                cleanItem,
                                teamLogic.values.currentTeamId ?? undefined,
                                propertyFilterFromRecent
                            )
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
                })
            }
        },

        infiniteListResultsReceived: ({ groupType, results }) => {
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
        },
    })),
])
