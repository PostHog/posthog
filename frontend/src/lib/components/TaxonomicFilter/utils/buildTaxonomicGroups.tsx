import clsx from 'clsx'
import { combineUrl } from 'kea-router'

import { IconFlag, IconServer } from '@posthog/icons'

import {
    buildAutocaptureSeriesShortcuts,
    buildEventTypeFilterShortcuts,
} from 'lib/components/TaxonomicFilter/eventTypeShortcuts'
import { RECENT_PINNED_TAB_DEFINITIONS } from 'lib/components/TaxonomicFilter/recentPinnedTabDefinitions'
import {
    DataWarehousePopoverField,
    SimpleOption,
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { withKeywordShortcuts } from 'lib/components/TaxonomicFilter/utils/keywordShortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconCohort } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { isString } from 'lib/utils/guards'
import { pluralize } from 'lib/utils/strings'
import {
    getEventDefinitionIcon,
    getEventMetadataDefinitionIcon,
    getPersonPropertyDefinitionIcon,
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
import { SavedFiltersTaxonomicGroup } from 'scenes/session-recordings/filters/SavedFiltersTaxonomicGroup'

import { actionsModel } from '~/models/actionsModel'
import { dashboardsModel } from '~/models/dashboardsModel'
import { AnyDataNode, DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'
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

import { InlineHogQLEditor } from '../InlineHogQLEditor'

const TRAFFIC_TYPE_VIRTUAL_PROPERTIES = [
    '$virt_is_bot',
    '$virt_traffic_type',
    '$virt_traffic_category',
    '$virt_bot_name',
]

// Stable reference for CohortsWithAllUsers options to prevent cascading re-renders.
// taxonomicGroups has 14 dependencies that change during initial mount. Each change creates
// new group objects with inline options arrays, causing rawLocalItems → fuse → localItems →
// items → selectedItem reference changes. With CohortsWithAllUsers, selectedItemHasPopover
// returns true (getValue returns 'all'), so ControlledDefinitionPopover renders and its
// useEffect dispatches setDefinition on every selectedItem change, triggering kea store updates
// that combined with react-window's layout effect setState exceed React's 50-update limit.
const COHORTS_WITH_ALL_USERS_OPTIONS: CohortType[] = [{ id: 'all', name: 'All Users*' } as unknown as CohortType]

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

/**
 * Pure inputs for buildTaxonomicGroups. Mirrors the dependency list of the
 * `taxonomicGroups` selector in taxonomicFilterLogic.tsx — keep in sync.
 */
export interface BuildTaxonomicGroupsContext {
    currentTeam: TeamType
    projectId: number | null
    groupAnalyticsTaxonomicGroups: TaxonomicFilterGroup[]
    groupAnalyticsTaxonomicGroupNames: TaxonomicFilterGroup[]
    eventNames: string[]
    /**
     * Distinct promoted properties for events currently in context. Surfaced first in the
     * SuggestedFilters tab so the team's chosen "summary" property is one click away.
     */
    promotedPropertiesForContextEvents?: string[]
    schemaColumns: DatabaseSchemaField[]
    schemaColumnsLoading: boolean | undefined
    metadataSource: AnyDataNode
    suggestedFiltersLabel: string | undefined
    propertyFilters: {
        excludedProperties: Partial<Record<TaxonomicFilterGroupType, (string | number | null)[]>>
        propertyAllowList?: Partial<Record<TaxonomicFilterGroupType, (string | number | null)[]>>
    }
    eventMetadataPropertyDefinitions: PropertyDefinition[]
    personMetadataPropertyDefinitions: PropertyDefinition[]
    maxContextOptions: MaxContextTaxonomicFilterOption[]
    hideBehavioralCohorts: boolean
    endpointFilters: Record<string, any> | undefined
    hogQLExpressionComponentProps: {
        globals?: Record<string, any>
        showBreakdownLabelHint: boolean
    }
    featureFlags: Record<string, boolean | string | undefined>
}

export function buildTaxonomicGroups(ctx: BuildTaxonomicGroupsContext): TaxonomicFilterGroup[] {
    const {
        currentTeam,
        projectId,
        groupAnalyticsTaxonomicGroups,
        groupAnalyticsTaxonomicGroupNames,
        eventNames,
        promotedPropertiesForContextEvents = [],
        schemaColumns,
        schemaColumnsLoading,
        metadataSource,
        suggestedFiltersLabel,
        propertyFilters,
        eventMetadataPropertyDefinitions,
        personMetadataPropertyDefinitions,
        maxContextOptions,
        hideBehavioralCohorts,
        endpointFilters,
        hogQLExpressionComponentProps,
        featureFlags,
    } = ctx
    const { id: teamId } = currentTeam
    const { excludedProperties, propertyAllowList } = propertyFilters
    // Opt the cohort picker into the trimmed `?basic=true` payload (drops the
    // filters/query/groups JSON the picker never reads). Gated by a flag so the
    // smaller response shape can be rolled out and rolled back independently.
    const cohortsEndpointParams = featureFlags[FEATURE_FLAGS.COHORTS_TAXONOMIC_BASIC_LIST] ? { basic: true } : undefined
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
            excludedProperties: excludedProperties?.[TaxonomicFilterGroupType.Events]?.filter(isString) ?? [],
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
            propertyAllowList: propertyAllowList?.[TaxonomicFilterGroupType.EventProperties]?.filter(isString),
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
                const coreDefinition = getCoreFilterDefinition(option.id, TaxonomicFilterGroupType.EventMetadata)
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
            excludedProperties: excludedProperties?.[TaxonomicFilterGroupType.EventFeatureFlags]?.filter(isString),
            ...propertyTaxonomicGroupProps(),
        },
        {
            name: 'Issues',
            searchPlaceholder: 'issues',
            type: TaxonomicFilterGroupType.ErrorTrackingIssues,
            options: Object.entries(CORE_FILTER_DEFINITIONS_BY_GROUP[TaxonomicFilterGroupType.ErrorTrackingIssues])
                .map(([key, { label }]) => ({
                    value: key,
                    name: label,
                }))
                .filter((o) => !excludedProperties[TaxonomicFilterGroupType.ErrorTrackingIssues]?.includes(o.value)),
            getName: (option) => option.name,
            getValue: (option) => option.value,
            valuesEndpoint: (key) => `api/environments/${projectId}/error_tracking/issues/values?key=` + key,
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
                    (o) => !excludedProperties[TaxonomicFilterGroupType.RevenueAnalyticsProperties]?.includes(o.value)
                ),
            getIcon: getRevenueAnalyticsDefinitionIcon,
            getName: (option: PropertyDefinition) => {
                const coreDefinition = getCoreFilterDefinition(
                    option.id,
                    TaxonomicFilterGroupType.RevenueAnalyticsProperties
                )

                return coreDefinition ? coreDefinition.label : option.name
            },
            getValue: (option: PropertyDefinition) => option.id,
            valuesEndpoint: (key) => {
                return `api/environments/${projectId}/revenue_analytics/taxonomy/values?key=${encodeURIComponent(key)}`
            },
            getPopoverHeader: () => 'Revenue analytics properties',
        },
        {
            name: 'Logs',
            searchPlaceholder: 'logs',
            type: TaxonomicFilterGroupType.Logs,
            options: [
                { key: 'message', name: 'message', propertyFilterType: 'log' },
                { key: 'severity_level', name: 'severity_level', propertyFilterType: 'log' },
                { key: 'trace_id', name: 'trace_id', propertyFilterType: 'log' },
                { key: 'span_id', name: 'span_id', propertyFilterType: 'log' },
            ].filter((o) => !excludedProperties[TaxonomicFilterGroupType.Logs]?.includes(o.key)),
            localItemsSearch: (items: any[], q: string): any[] => {
                if (!q) {
                    return items
                }
                const matches = items.filter((item) => item.name?.toLowerCase().includes(q.toLowerCase()))
                // Mirrors the legacy Logs group in taxonomicFilterLogic: the free-text message-search
                // item only makes sense where picking `message` does.
                if (excludedProperties[TaxonomicFilterGroupType.Logs]?.includes('message')) {
                    return matches
                }
                return [
                    {
                        key: 'message',
                        name: 'Search log message for "' + q + '"',
                        value: q,
                        propertyFilterType: 'log',
                    },
                ].concat(matches)
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
            name: 'Metric attributes',
            searchPlaceholder: 'attributes',
            type: TaxonomicFilterGroupType.MetricAttributes,
            endpoint: combineUrl(`api/environments/${projectId}/metrics/attributes`, {
                ...endpointFilters,
            }).url,
            valuesEndpoint: (key) =>
                combineUrl(`api/environments/${projectId}/metrics/attribute_values`, {
                    key: key,
                    ...endpointFilters,
                }).url,
            getName: (option: SimpleOption) => option.name,
            getValue: (option: SimpleOption) => option.name,
            getPopoverHeader: () => 'Metric attributes',
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
                attribute_type: 'span_attribute',
                search_values: 'true',
                ...endpointFilters,
            }).url,
            valuesEndpoint: (key) =>
                combineUrl(`api/environments/${projectId}/tracing/spans/values`, {
                    attribute_type: 'span_attribute',
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
                attribute_type: 'span_resource_attribute',
                search_values: 'true',
                ...endpointFilters,
            }).url,
            valuesEndpoint: (key) =>
                combineUrl(`api/environments/${projectId}/tracing/spans/values`, {
                    attribute_type: 'span_resource_attribute',
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
            propertyAllowList: propertyAllowList?.[TaxonomicFilterGroupType.PersonProperties]?.filter(isString),
            ...propertyTaxonomicGroupProps(CORE_FILTER_DEFINITIONS_BY_GROUP.person_properties),
            getIcon: getPersonPropertyDefinitionIcon,
        },
        {
            name: 'Person metadata',
            searchPlaceholder: 'person metadata',
            type: TaxonomicFilterGroupType.PersonMetadata,
            options: personMetadataPropertyDefinitions,
            getIcon: getPropertyDefinitionIcon,
            getName: (option: PropertyDefinition) => {
                const coreDefinition = getCoreFilterDefinition(option.id, TaxonomicFilterGroupType.PersonMetadata)
                return coreDefinition ? coreDefinition.label : option.name
            },
            getValue: (option: PropertyDefinition) => option.id,
            getPopoverHeader: () => 'Person metadata',
        },
        {
            name: 'Cohorts',
            searchPlaceholder: 'cohorts',
            type: TaxonomicFilterGroupType.Cohorts,
            endpoint: combineUrl(`api/projects/${projectId}/cohorts/`, cohortsEndpointParams).url,
            value: 'cohorts',
            // See taxonomicFilterLogic — cohort populations comfortably fit
            // in one page; cache the first 100 and fuse-filter typed
            // queries locally to avoid per-keystroke round-trips.
            clientFilterFirstPage: true,
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
            endpoint: combineUrl(`api/projects/${projectId}/cohorts/`, cohortsEndpointParams).url,
            clientFilterFirstPage: true,
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
            getValue: (person: PersonType) => person.distinct_ids?.[0],
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
                const isInactive = featureFlag.active === false
                return isInactive ? `${name} (disabled)` : name
            },
            getValue: (featureFlag: FeatureFlagType) => featureFlag.id || '',
            getPopoverHeader: () => `Feature Flags`,
            getIcon: (featureFlag: FeatureFlagType) => (
                <IconFlag className={clsx('size-4', featureFlag.active === false && 'text-muted-alt opacity-50')} />
            ),
            // Recently-used entries are stored stripped of `active`, so treat only an explicit
            // `false` as disabled — otherwise recent flags are wrongly disabled and unselectable.
            // Keep in sync with the Feature Flags group in taxonomicFilterLogic.tsx.
            getIsDisabled: (featureFlag: FeatureFlagType) => featureFlag.active === false,
            localItemsSearch: (items: TaxonomicDefinitionTypes[], query: string): TaxonomicDefinitionTypes[] => {
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
            excludedProperties: excludedProperties?.[TaxonomicFilterGroupType.FeatureFlags]?.filter(isString),
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
            // The headless menu derives the committed value via group.getValue(item);
            // without this the SQL expression resolves to null and the selection is
            // silently dropped on save.
            getValue: (option) => (option as { value?: TaxonomicFilterValue }).value ?? option.name,
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
                {
                    key: 'click_count',
                    name: getFilterLabel('click_count', TaxonomicFilterGroupType.Replay),
                    propertyFilterType: PropertyFilterType.Recording,
                },
                {
                    key: 'keypress_count',
                    name: getFilterLabel('keypress_count', TaxonomicFilterGroupType.Replay),
                    propertyFilterType: PropertyFilterType.Recording,
                },
                {
                    key: 'mouse_activity_count',
                    name: getFilterLabel('mouse_activity_count', TaxonomicFilterGroupType.Replay),
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
            // Recording playlists are tiny per team — cache the first page
            // and let fuse handle keystrokes locally.
            clientFilterFirstPage: true,
            render: SavedFiltersTaxonomicGroup,
            getName: (filter: SessionRecordingPlaylistType) => filter.name || filter.derived_name || 'Unnamed',
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
        ...RECENT_PINNED_TAB_DEFINITIONS,
        ...groupAnalyticsTaxonomicGroups,
        ...groupAnalyticsTaxonomicGroupNames,
    ]

    return groups
}
