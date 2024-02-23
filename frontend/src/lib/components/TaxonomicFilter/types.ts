import Fuse from 'fuse.js'
import { LogicWrapper } from 'kea'
import { DataWarehouseTableType } from 'scenes/data-warehouse/types'

import { AnyDataNode } from '~/queries/schema'
import {
    ActionType,
    CohortType,
    EventDefinition,
    PersonProperty,
    PropertyDefinition,
    PropertyFilterType,
} from '~/types'

export interface SimpleOption {
    name: string
    propertyFilterType?: PropertyFilterType
}

export interface TaxonomicFilterProps {
    groupType?: TaxonomicFilterGroupType
    value?: TaxonomicFilterValue
    onChange?: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue, item: any) => void
    onClose?: () => void
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    taxonomicFilterLogicKey?: string
    optionsFromProp?: Partial<Record<TaxonomicFilterGroupType, SimpleOption[]>>
    eventNames?: string[]
    height?: number
    width?: number
    popoverEnabled?: boolean
    selectFirstItem?: boolean
    /** use to filter results in a group by name, currently only working for EventProperties */
    excludedProperties?: { [key in TaxonomicFilterGroupType]?: TaxonomicFilterValue[] }
    propertyAllowList?: { [key in TaxonomicFilterGroupType]?: string[] } // only return properties in this list, currently only working for EventProperties and PersonProperties
    metadataSource?: AnyDataNode
}

export interface TaxonomicFilterLogicProps extends TaxonomicFilterProps {
    taxonomicFilterLogicKey: string
}

export type TaxonomicFilterValue = string | number | null

export type TaxonomicFilterRender = (props: {
    value?: TaxonomicFilterValue
    onChange: (value: TaxonomicFilterValue) => void
}) => JSX.Element | null

export interface TaxonomicFilterGroup {
    name: string
    searchPlaceholder: string
    type: TaxonomicFilterGroupType
    /** Component to show instead of the usual taxonomic list. */
    render?: TaxonomicFilterRender
    endpoint?: string
    /** If present, will be used instead of "endpoint" until the user presses "expand results". */
    scopedEndpoint?: string
    expandLabel?: (props: { count: number; expandedCount: number }) => React.ReactNode
    options?: Record<string, any>[]
    logic?: LogicWrapper
    value?: string
    searchAlias?: string
    valuesEndpoint?: (key: string) => string
    getName?: (instance: any) => string
    getValue?: (instance: any) => TaxonomicFilterValue
    getPopoverHeader: (instance: any) => string
    getIcon?: (instance: any) => JSX.Element
    groupTypeIndex?: number
    getFullDetailUrl?: (instance: any) => string
    excludedProperties?: string[]
    propertyAllowList?: string[]
    /** Passed to the component specified via the `render` key */
    componentProps?: Record<string, any>
}

export enum TaxonomicFilterGroupType {
    // Person and event metadata that isn't present in properties
    Metadata = 'metadata',
    Actions = 'actions',
    Cohorts = 'cohorts',
    CohortsWithAllUsers = 'cohorts_with_all',
    DataWarehouse = 'data_warehouse',
    Elements = 'elements',
    Events = 'events',
    EventProperties = 'event_properties',
    EventFeatureFlags = 'event_feature_flags',
    NumericalEventProperties = 'numerical_event_properties',
    PersonProperties = 'person_properties',
    PageviewUrls = 'pageview_urls',
    Screens = 'screens',
    CustomEvents = 'custom_events',
    Wildcards = 'wildcard',
    GroupsPrefix = 'groups',
    // Types for searching
    Persons = 'persons',
    FeatureFlags = 'feature_flags',
    Insights = 'insights',
    Experiments = 'experiments',
    Plugins = 'plugins',
    Dashboards = 'dashboards',
    GroupNamesPrefix = 'name_groups',
    Sessions = 'sessions',
    HogQLExpression = 'hogql_expression',
    Notebooks = 'notebooks',
}

export interface InfiniteListLogicProps extends TaxonomicFilterLogicProps {
    listGroupType: TaxonomicFilterGroupType
}

export interface ListStorage {
    results: TaxonomicDefinitionTypes[]
    searchQuery?: string // Query used for the results currently in state
    count: number
    expandedCount?: number
    queryChanged?: boolean
    first?: boolean
}

export interface LoaderOptions {
    offset: number
    limit: number
}

export type ListFuse = Fuse<{
    name: string
    item: EventDefinition | CohortType
}> // local alias for typegen

export type TaxonomicDefinitionTypes =
    | EventDefinition
    | PropertyDefinition
    | CohortType
    | ActionType
    | PersonProperty
    | DataWarehouseTableType
