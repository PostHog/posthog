import clsx from 'clsx'
import Fuse from 'fuse.js'
import { BuiltLogic, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl } from 'kea-router'
import posthog from 'posthog-js'

import { IconEye, IconFlag, IconPerson, IconServer } from '@posthog/icons'

import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'
import { taxonomicFilterPreferencesLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterPreferencesLogic'
import {
    DataWarehousePopoverField,
    ExcludedProperties,
    ListStorage,
    QuickFilterItem,
    SelectedProperties,
    SimpleOption,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
    isQuickFilterItem,
} from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { IconCohort } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, isString, pluralize, toParams } from 'lib/utils'
import { getProjectEventExistence } from 'lib/utils/getAppContext'
import {
    getEventDefinitionIcon,
    getEventMetadataDefinitionIcon,
    getPropertyDefinitionIcon,
    getRevenueAnalyticsDefinitionIcon,
} from 'scenes/data-management/events/DefinitionHeader'
import { dataWarehouseJoinsLogic } from 'scenes/data-warehouse/external/dataWarehouseJoinsLogic'
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
import {
    ReplayTaxonomicFilters,
    replayTaxonomicFiltersProperties,
} from 'scenes/session-recordings/filters/ReplayTaxonomicFilters'
import { teamLogic } from 'scenes/teamLogic'

import { actionsModel } from '~/models/actionsModel'
import { dashboardsModel } from '~/models/dashboardsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel, updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { AnyDataNode, DatabaseSchemaField, DatabaseSchemaTable, NodeKind } from '~/queries/schema/schema-general'
import { getCoreFilterDefinition, getFilterLabel } from '~/taxonomy/helpers'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import {
    ActionType,
    CohortType,
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
    PropertyOperator,
    QueryBasedInsightModel,
    TeamType,
} from '~/types'

import { HogFlowTaxonomicFilters } from 'products/workflows/frontend/Workflows/hogflows/filters/HogFlowTaxonomicFilters'

import { InlineHogQLEditor } from './InlineHogQLEditor'
import type { taxonomicFilterLogicType } from './taxonomicFilterLogicType'

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
    verified: boolean = false
): Pick<TaxonomicFilterGroup, 'getPopoverHeader' | 'getIcon'> => ({
    getPopoverHeader: (propertyDefinition: PropertyDefinition): string => {
        if (verified || !!CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties[propertyDefinition.name]) {
            return 'PostHog property'
        }
        return 'Property'
    },
    getIcon: getPropertyDefinitionIcon,
})

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

interface EventContext {
    key: string
    label: string
}

function operatorLabel(op: PropertyOperator): string {
    return op === PropertyOperator.Exact ? '=' : 'containing'
}

export function buildQuickFilterSuggestions(
    q: string,
    groupTypes: TaxonomicFilterGroupType[] | undefined,
    eventExistence: { hasPageview: boolean; hasScreen: boolean } = { hasPageview: true, hasScreen: true }
): QuickFilterItem[] {
    if (!q) {
        return []
    }

    const isEventMode =
        !!groupTypes &&
        (groupTypes.includes(TaxonomicFilterGroupType.Events) || groupTypes.includes(TaxonomicFilterGroupType.Actions))

    const pageviewLabel = getFilterLabel('$pageview', TaxonomicFilterGroupType.Events)
    const currentUrlLabel = getFilterLabel('$current_url', TaxonomicFilterGroupType.EventProperties)
    const screenLabel = getFilterLabel('$screen', TaxonomicFilterGroupType.Events)
    const screenNameLabel = getFilterLabel('$screen_name', TaxonomicFilterGroupType.EventProperties)
    const emailLabel = getFilterLabel('email', TaxonomicFilterGroupType.PersonProperties)

    const pageview: EventContext = { key: '$pageview', label: pageviewLabel }
    const screen: EventContext = { key: '$screen', label: screenLabel }

    const makeItem = (
        propertyKey: string,
        propertyLabel: string,
        propertyFilterType: PropertyFilterType.Event | PropertyFilterType.Person,
        op: PropertyOperator,
        event?: EventContext
    ): QuickFilterItem => ({
        _type: 'quick_filter',
        name:
            isEventMode && event
                ? `${event.label} with ${propertyLabel} ${operatorLabel(op)} "${q}"`
                : `${propertyLabel} ${operatorLabel(op)} "${q}"`,
        filterValue: q,
        operator: op,
        propertyKey,
        propertyFilterType,
        ...(event ? { eventName: event.key } : {}),
    })

    const isEmail = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(q)
    const isUrl = /^https?:\/\/.+/.test(q)

    const results: QuickFilterItem[] = []

    if (isEmail) {
        if (isEventMode) {
            results.push(
                makeItem('email', emailLabel, PropertyFilterType.Person, PropertyOperator.Exact, pageview),
                makeItem('email', emailLabel, PropertyFilterType.Person, PropertyOperator.Exact, screen)
            )
        } else {
            results.push(makeItem('email', emailLabel, PropertyFilterType.Person, PropertyOperator.Exact))
        }
    }

    if (isUrl) {
        results.push(
            makeItem('$current_url', currentUrlLabel, PropertyFilterType.Event, PropertyOperator.Exact, pageview)
        )
    }

    results.push(
        makeItem('$current_url', currentUrlLabel, PropertyFilterType.Event, PropertyOperator.IContains, pageview),
        makeItem('$screen_name', screenNameLabel, PropertyFilterType.Event, PropertyOperator.IContains, screen)
    )

    if (isEventMode) {
        results.push({
            _type: 'quick_filter',
            name: `Clicked an element with text "${q}"`,
            filterValue: q,
            operator: PropertyOperator.IContains,
            propertyKey: '$el_text',
            propertyFilterType: PropertyFilterType.Event,
            eventName: '$autocapture',
            extraProperties: [
                {
                    key: '$event_type',
                    value: 'click',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
        })
    }

    if (!isEmail) {
        if (isEventMode) {
            results.push(
                makeItem('email', emailLabel, PropertyFilterType.Person, PropertyOperator.IContains, pageview),
                makeItem('email', emailLabel, PropertyFilterType.Person, PropertyOperator.IContains, screen)
            )
        } else {
            results.push(makeItem('email', emailLabel, PropertyFilterType.Person, PropertyOperator.IContains))
        }
    }

    return results.filter((item) => {
        if (item.eventName === '$pageview' && !eventExistence.hasPageview) {
            return false
        }
        if (item.eventName === '$screen' && !eventExistence.hasScreen) {
            return false
        }
        return true
    })
}

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
            dataWarehouseJoinsLogic,
            ['columnsJoinedToPersons'],
            propertyDefinitionsModel,
            ['eventMetadataPropertyDefinitions'],
            taxonomicFilterPreferencesLogic,
            ['eventOrdering'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions(() => ({
        moveUp: true,
        moveDown: true,
        selectSelected: true,
        enableMouseInteractions: true,
        tabLeft: true,
        tabRight: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setActiveTab: (activeTab: TaxonomicFilterGroupType) => ({ activeTab }),
        selectItem: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue | null, item: any, originalQuery) => ({
            group,
            value,
            item,
            originalQuery,
        }),
        infiniteListResultsReceived: (groupType: TaxonomicFilterGroupType, results: ListStorage) => ({
            groupType,
            results,
        }),
        appendTopMatch: (item: TaxonomicDefinitionTypes & { group: TaxonomicFilterGroupType }) => ({ item }),
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
                if (groupTypes.includes(TaxonomicFilterGroupType.SuggestedFilters)) {
                    return TaxonomicFilterGroupType.SuggestedFilters
                }
                return selectors.groupType(state) || groupTypes[0]
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
                appendTopMatch: (
                    state: (TaxonomicDefinitionTypes & { group: TaxonomicFilterGroupType })[],
                    { item }: { item: TaxonomicDefinitionTypes & { group: TaxonomicFilterGroupType } }
                ) => {
                    const existingIndex = state.findIndex((i) => i.group === item.group)
                    if (existingIndex >= 0) {
                        const next = [...state]
                        next[existingIndex] = item
                        return next
                    }
                    return [...state, item]
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
        schemaColumns: [() => [(_, props) => props.schemaColumns], (schemaColumns) => schemaColumns ?? []],
        maxContextOptions: [
            () => [(_, props) => props.maxContextOptions],
            (maxContextOptions) => maxContextOptions ?? [],
        ],
        dataWarehousePopoverFields: [
            () => [(_, props) => props.dataWarehousePopoverFields],
            (dataWarehousePopoverFields) => dataWarehousePopoverFields ?? {},
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
        endpointFilters: [
            () => [(_, props) => props.endpointFilters],
            (endpointFilters: Record<string, any>) => endpointFilters,
        ],
        taxonomicGroups: [
            (s, p) => [
                s.currentTeam,
                s.currentProjectId,
                s.groupAnalyticsTaxonomicGroups,
                s.groupAnalyticsTaxonomicGroupNames,
                s.eventNames,
                s.schemaColumns,
                s.metadataSource,
                s.propertyFilters,
                s.eventMetadataPropertyDefinitions,
                s.eventOrdering,
                s.maxContextOptions,
                s.hideBehavioralCohorts,
                s.endpointFilters,
                p.taxonomicGroupTypes,
            ],
            (
                currentTeam: TeamType,
                projectId: number | null,
                groupAnalyticsTaxonomicGroups: TaxonomicFilterGroup[],
                groupAnalyticsTaxonomicGroupNames: TaxonomicFilterGroup[],
                eventNames: string[],
                schemaColumns: DatabaseSchemaField[],
                metadataSource: AnyDataNode,
                propertyFilters,
                eventMetadataPropertyDefinitions: PropertyDefinition[],
                eventOrdering: string | null,
                maxContextOptions: MaxContextTaxonomicFilterOption[],
                hideBehavioralCohorts: boolean,
                endpointFilters: Record<string, any> | undefined,
                propGroupTypes: TaxonomicFilterGroupType[] | undefined
            ): TaxonomicFilterGroup[] => {
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
                            ordering: eventOrdering ?? undefined,
                        }).url,
                        excludedProperties:
                            excludedProperties?.[TaxonomicFilterGroupType.Events]?.filter(isString) ?? [],
                        getName: (eventDefinition: Record<string, any>) => eventDefinition.name,
                        getValue: (eventDefinition: Record<string, any>) =>
                            'id' in eventDefinition ? eventDefinition.name : eventDefinition.value,
                        ...eventTaxonomicGroupProps,
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
                        getName: (table: DatabaseSchemaTable) => table.name,
                        getValue: (table: DatabaseSchemaTable) => table.name,
                        getPopoverHeader: () => 'Data Warehouse Table',
                        getIcon: () => <IconServer />,
                    },
                    ...(schemaColumns.length > 0
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
                        logic: dataWarehouseJoinsLogic,
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
                        ...propertyTaxonomicGroupProps(true),
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
                        getName: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                        getValue: (propertyDefinition: PropertyDefinition) => propertyDefinition.name,
                        excludedProperties:
                            excludedProperties?.[TaxonomicFilterGroupType.EventProperties]?.filter(isString),
                        propertyAllowList:
                            propertyAllowList?.[TaxonomicFilterGroupType.EventProperties]?.filter(isString),
                        ...propertyTaxonomicGroupProps(),
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
                        ...propertyTaxonomicGroupProps(true),
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
                    {
                        name: 'Pageview URLs',
                        searchPlaceholder: 'pageview URLs',
                        type: TaxonomicFilterGroupType.PageviewUrls,
                        endpoint: `api/environments/${teamId}/events/values/?key=$current_url`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Pageview URL`,
                    },
                    {
                        name: 'Screens',
                        searchPlaceholder: 'screens',
                        type: TaxonomicFilterGroupType.Screens,
                        endpoint: `api/environments/${teamId}/events/values/?key=$screen_name`,
                        searchAlias: 'value',
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => `Screen`,
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
                        componentProps: { metadataSource },
                    },
                    {
                        name: 'Replay',
                        searchPlaceholder: 'Replay',
                        categoryLabel: (count: number) => 'Replay' + (count > 0 ? `: ${count}` : ''),
                        type: TaxonomicFilterGroupType.Replay,
                        render: ReplayTaxonomicFilters,
                        localItemsSearch: (
                            items: TaxonomicDefinitionTypes[],
                            q: string
                        ): TaxonomicDefinitionTypes[] => {
                            if (q.trim() === '') {
                                return items
                            }
                            const fuse = new Fuse(replayTaxonomicFiltersProperties, {
                                keys: ['label', 'key'],
                                threshold: 0.3,
                            })
                            return fuse.search(q).map((result) => result.item)
                        },
                        valuesEndpoint: (key) => {
                            if (key === 'visited_page') {
                                return (
                                    `api/environments/${teamId}/events/values/?key=` +
                                    'api/event/values/?key=' +
                                    encodeURIComponent('$current_url') +
                                    '&event_name=' +
                                    encodeURIComponent('$pageview')
                                )
                            }
                        },
                        getPopoverHeader: () => 'Replay',
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
                        name: 'Suggested filters',
                        searchPlaceholder: 'suggested filters',
                        categoryLabel: (count: number) => 'Suggested filters' + (count > 0 ? `: ${count}` : ''),
                        type: TaxonomicFilterGroupType.SuggestedFilters,
                        options: [],
                        localItemsSearch: (_items: TaxonomicDefinitionTypes[], q: string): QuickFilterItem[] =>
                            buildQuickFilterSuggestions(q, propGroupTypes, getProjectEventExistence()),
                        getIcon: (item: QuickFilterItem) =>
                            item.propertyFilterType === PropertyFilterType.Person ? <IconPerson /> : <IconEye />,
                        getName: (item: QuickFilterItem) => item.name,
                        getValue: (item: QuickFilterItem) => item.filterValue,
                        getPopoverHeader: () => 'Suggested filters',
                    },
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
        taxonomicGroupTypes: [
            (s, p) => [p.taxonomicGroupTypes, s.taxonomicGroups, s.featureFlags],
            (groupTypes, taxonomicGroups, featureFlags): TaxonomicFilterGroupType[] => {
                const availableGroupTypes = new Set(taxonomicGroups.map((group) => group.type))
                const quickFiltersEnabled = featureFlags[FEATURE_FLAGS.TAXONOMIC_QUICK_FILTERS] === 'test'
                const resolvedGroupTypes: TaxonomicFilterGroupType[] =
                    groupTypes || taxonomicGroups.map((group) => group.type)

                return resolvedGroupTypes.filter(
                    (groupType) =>
                        availableGroupTypes.has(groupType) &&
                        (groupType !== TaxonomicFilterGroupType.SuggestedFilters || quickFiltersEnabled)
                )
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
                            type &&
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
    }),
    listeners(({ actions, values, props }) => ({
        selectItem: ({ group, value, item, originalQuery }) => {
            if (item) {
                try {
                    const hasOriginalQuery = originalQuery && originalQuery.trim().length > 0
                    const hasName = item && item.name && item.name.trim().length > 0
                    const hasSwappedIn = hasOriginalQuery && hasName && item.name !== originalQuery
                    if (hasSwappedIn) {
                        posthog.capture('selected swapped in query in taxonomic filter', {
                            group: group.type,
                            value: value,
                            itemName: item.name,
                            originalQuery,
                            item,
                        })
                    }
                    if (isQuickFilterItem(item)) {
                        posthog.capture('taxonomic suggested filter selected', {
                            query: originalQuery,
                            filterName: item.name,
                            propertyKey: item.propertyKey,
                            operator: item.operator,
                            filterValue: item.filterValue,
                            propertyFilterType: item.propertyFilterType,
                            eventName: item.eventName,
                        })
                    } else {
                        posthog.capture('taxonomic non-suggested filter selected', {
                            group: group.type,
                            value,
                            activeTab: values.activeTab,
                        })
                    }
                } catch (e) {
                    posthog.captureException(e, { posthog_feature: 'taxonomic_filter_swapped_in_query' })
                }
                props.onChange?.(group, value, item, originalQuery)
            } else if (group.type === TaxonomicFilterGroupType.HogQLExpression && value) {
                props.onChange?.(group, value, item, originalQuery)
            } else if (props.onEnter) {
                // If the user pressed enter on a group with no item selected, we want to pass the original query
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

        setSearchQuery: async ({ searchQuery }, breakpoint) => {
            const { activeTaxonomicGroup, infiniteListCounts } = values

            // does replay have 0 results
            // if you have a render function, and replay does, then infiniteListCounts will always be 1 or more 🤷
            const shouldTabRightBecauseReplay =
                activeTaxonomicGroup &&
                activeTaxonomicGroup.type === TaxonomicFilterGroupType.Replay &&
                infiniteListCounts[activeTaxonomicGroup.type] === 1
            // or is this a Taxonomic group with a local data source, zero results after searching.
            const shouldOtherwiseTabRight =
                activeTaxonomicGroup &&
                activeTaxonomicGroup.type !== TaxonomicFilterGroupType.SuggestedFilters &&
                !activeTaxonomicGroup.endpoint &&
                infiniteListCounts[activeTaxonomicGroup.type] === 0
            if (shouldTabRightBecauseReplay || shouldOtherwiseTabRight) {
                actions.tabRight()
            }

            await breakpoint(500)
            if (searchQuery) {
                posthog.capture('taxonomic_filter_search_query', {
                    searchQuery,
                    groupType: activeTaxonomicGroup?.type,
                })
            }
        },

        infiniteListResultsReceived: ({ groupType, results }) => {
            const activeTabHasNoResults = groupType === values.activeTab && !results.count && !results.expandedCount

            if (activeTabHasNoResults && values.activeTab !== TaxonomicFilterGroupType.SuggestedFilters) {
                actions.tabRight()
            }

            if (
                values.activeTab === TaxonomicFilterGroupType.SuggestedFilters &&
                groupType !== TaxonomicFilterGroupType.SuggestedFilters
            ) {
                const logic = values.infiniteListLogics[groupType]
                if (logic?.isMounted()) {
                    const match = logic.values.topMatchForQuery
                    if (match) {
                        actions.appendTopMatch({
                            ...match,
                            group: groupType as TaxonomicFilterGroupType,
                        })
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

        setActiveTab: ({ activeTab }) => {
            if (values.taxonomicGroupTypes.includes(TaxonomicFilterGroupType.SuggestedFilters)) {
                posthog.capture('taxonomic filter tab switched', {
                    activeTab,
                    searchQuery: values.searchQuery,
                })
            }
        },
    })),
])
