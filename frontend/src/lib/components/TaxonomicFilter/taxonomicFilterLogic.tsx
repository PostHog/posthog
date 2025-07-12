import { IconServer } from '@posthog/icons'
import { actions, BuiltLogic, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl } from 'kea-router'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { infiniteListLogicType } from 'lib/components/TaxonomicFilter/infiniteListLogicType'
import { taxonomicFilterPreferencesLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterPreferencesLogic'
import {
    DataWarehousePopoverField,
    ListStorage,
    SimpleOption,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { IconCohort } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter, pluralize, toParams } from 'lib/utils'
import posthog from 'posthog-js'
import {
    getEventDefinitionIcon,
    getEventMetadataDefinitionIcon,
    getPropertyDefinitionIcon,
    getRevenueAnalyticsDefinitionIcon,
} from 'scenes/data-management/events/DefinitionHeader'
import { dataWarehouseJoinsLogic } from 'scenes/data-warehouse/external/dataWarehouseJoinsLogic'
import { dataWarehouseSceneLogic } from 'scenes/data-warehouse/settings/dataWarehouseSceneLogic'
import { experimentsLogic } from 'scenes/experiments/experimentsLogic'
import { MaxContextTaxonomicFilterOption } from 'scenes/max/maxTypes'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { projectLogic } from 'scenes/projectLogic'
import { ReplayTaxonomicFilters } from 'scenes/session-recordings/filters/ReplayTaxonomicFilters'
import { teamLogic } from 'scenes/teamLogic'

import { actionsModel } from '~/models/actionsModel'
import { dashboardsModel } from '~/models/dashboardsModel'
import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel, updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { AnyDataNode, DatabaseSchemaField, DatabaseSchemaTable, NodeKind } from '~/queries/schema/schema-general'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
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
    NotebookType,
    PersonProperty,
    PersonType,
    PropertyDefinition,
    PropertyDefinitionType,
    QueryBasedInsightModel,
} from '~/types'

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
            ['currentTeamId'],
            projectLogic,
            ['currentProjectId'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            dataWarehouseSceneLogic, // This logic needs to be connected to stop the popover from erroring out
            ['dataWarehouseTables'],
            dataWarehouseJoinsLogic,
            ['columnsJoinedToPersons'],
            propertyDefinitionsModel,
            ['eventMetadataPropertyDefinitions'],
            taxonomicFilterPreferencesLogic,
            ['eventOrdering'],
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
                return selectors.groupType(state) || selectors.taxonomicGroupTypes(state)[0]
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
    })),
    selectors({
        selectedItemMeta: [() => [(_, props) => props.filter], (filter) => filter],
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
            (excludedProperties) => excludedProperties ?? {},
        ],
        propertyAllowList: [
            () => [(_, props) => props.propertyAllowList],
            (propertyAllowList) => propertyAllowList as TaxonomicFilterLogicProps['propertyAllowList'],
        ],
        propertyFilters: [
            (s) => [s.excludedProperties, s.propertyAllowList],
            (
                excludedProperties: Record<string, any>,
                propertyAllowList: TaxonomicFilterLogicProps['propertyAllowList']
            ) => ({ excludedProperties, propertyAllowList }),
        ],
        allowNonCapturedEvents: [
            () => [(_, props) => props.allowNonCapturedEvents],
            (allowNonCapturedEvents: boolean | undefined) => allowNonCapturedEvents ?? false,
        ],
        taxonomicGroups: [
            (s) => [
                s.currentTeamId,
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
            ],
            (
                teamId: number | null,
                projectId: number | null,
                groupAnalyticsTaxonomicGroups: TaxonomicFilterGroup[],
                groupAnalyticsTaxonomicGroupNames: TaxonomicFilterGroup[],
                eventNames: string[],
                schemaColumns: DatabaseSchemaField[],
                metadataSource: AnyDataNode,
                propertyFilters: { excludedProperties: any; propertyAllowList: any },
                eventMetadataPropertyDefinitions: PropertyDefinition[],
                eventOrdering: string | null,
                maxContextOptions: MaxContextTaxonomicFilterOption[]
            ): TaxonomicFilterGroup[] => {
                const { excludedProperties, propertyAllowList } = propertyFilters
                const groups: TaxonomicFilterGroup[] = [
                    {
                        name: 'Events',
                        searchPlaceholder: 'events',
                        type: TaxonomicFilterGroupType.Events,
                        options: [{ name: 'All events', value: null }].filter(
                            (o) => !excludedProperties[TaxonomicFilterGroupType.Events]?.includes(o.value)
                        ),
                        // the default ordering for the API is "both"
                        // so we don't need to add an ordering param in that case
                        endpoint: combineUrl(`api/projects/${projectId}/event_definitions`, {
                            event_type: EventDefinitionType.Event,
                            exclude_hidden: true,
                            ordering: eventOrdering ?? undefined,
                        }).url,
                        getName: (eventDefinition: Record<string, any>) => eventDefinition.name,
                        getValue: (eventDefinition: Record<string, any>) =>
                            // Use the property's "name" when available, or "value" if a local option
                            'id' in eventDefinition ? eventDefinition.name : eventDefinition.value,
                        ...eventTaxonomicGroupProps,
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
                        logic: dataWarehouseSceneLogic,
                        value: 'dataWarehouseTablesAndViews',
                        getName: (table: DatabaseSchemaTable) => table.name,
                        getValue: (table: DatabaseSchemaTable) => table.name,
                        getPopoverHeader: () => 'Data Warehouse Table',
                        getIcon: () => <IconServer />,
                    },
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
                        excludedProperties: excludedProperties?.[TaxonomicFilterGroupType.EventProperties],
                        propertyAllowList: propertyAllowList?.[TaxonomicFilterGroupType.EventProperties],
                        ...propertyTaxonomicGroupProps(),
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
                        excludedProperties: excludedProperties?.[TaxonomicFilterGroupType.EventFeatureFlags],
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
                        name: 'Log attributes',
                        searchPlaceholder: 'logs',
                        type: TaxonomicFilterGroupType.LogAttributes,
                        endpoint: combineUrl(`api/environments/${projectId}/logs/attributes`, {
                            is_feature_flag: false,
                            ...(eventNames.length > 0 ? { event_names: eventNames } : {}),
                            properties: propertyAllowList?.[TaxonomicFilterGroupType.EventProperties]
                                ? propertyAllowList[TaxonomicFilterGroupType.EventProperties].join(',')
                                : undefined,
                            exclude_hidden: true,
                        }).url,
                        valuesEndpoint: (key) => `api/environments/${projectId}/logs/values?key=` + key,
                        getName: (option: SimpleOption) => option.name,
                        getValue: (option: SimpleOption) => option.name,
                        getPopoverHeader: () => 'Log attributes',
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
                        propertyAllowList: propertyAllowList?.[TaxonomicFilterGroupType.PersonProperties],
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
                    },
                    {
                        name: 'Cohorts',
                        searchPlaceholder: 'cohorts',
                        type: TaxonomicFilterGroupType.CohortsWithAllUsers,
                        endpoint: combineUrl(`api/projects/${projectId}/cohorts/`).url,
                        options: [{ id: 'all', name: 'All Users*' }],
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
                        type: TaxonomicFilterGroupType.FeatureFlags,
                        endpoint: combineUrl(`api/projects/${projectId}/feature_flags/`).url,
                        getName: (featureFlag: FeatureFlagType) => featureFlag.key || featureFlag.name,
                        getValue: (featureFlag: FeatureFlagType) => featureFlag.id || '',
                        getPopoverHeader: () => `Feature Flags`,
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
                                  options: propertyAllowList[TaxonomicFilterGroupType.SessionProperties]?.map(
                                      (property: string) => ({
                                          name: property,
                                          value: property,
                                      })
                                  ),
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
                        type: TaxonomicFilterGroupType.HogQLExpression,
                        render: InlineHogQLEditor,
                        getPopoverHeader: () => 'SQL expression',
                        componentProps: { metadataSource },
                    },
                    {
                        name: 'Replay',
                        searchPlaceholder: 'Replay',
                        type: TaxonomicFilterGroupType.Replay,
                        render: ReplayTaxonomicFilters,
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
                            const Icon = option.icon as React.ComponentType
                            if (Icon) {
                                return <Icon />
                            }
                            return <></>
                        },
                        getPopoverHeader: () => 'On this page',
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
            (s, p) => [p.taxonomicGroupTypes, s.taxonomicGroups],
            (groupTypes, taxonomicGroups): TaxonomicFilterGroupType[] =>
                groupTypes || taxonomicGroups.map((g) => g.type),
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

            // Taxonomic group with a local data source, zero results after searching.
            // Open the next tab.
            if (
                activeTaxonomicGroup &&
                !activeTaxonomicGroup.endpoint &&
                infiniteListCounts[activeTaxonomicGroup.type] === 0
            ) {
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
            // Open the next tab if no results on an active tab.
            const activeTabHasNoResults = groupType === values.activeTab && !results.count && !results.expandedCount
            const onReplayTabWithSomeSearchResults =
                values.activeTab === TaxonomicFilterGroupType.Replay && results.count > 0

            if (activeTabHasNoResults || onReplayTabWithSomeSearchResults) {
                actions.tabRight()
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
