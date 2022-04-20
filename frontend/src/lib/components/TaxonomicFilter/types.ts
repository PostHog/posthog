import { LogicWrapper } from 'kea'
import { ActionType, CohortType, EventDefinition, PersonProperty, PropertyDefinition } from '~/types'
import Fuse from 'fuse.js'

export interface SimpleOption {
    name: string
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
}

export interface TaxonomicFilterLogicProps extends TaxonomicFilterProps {
    taxonomicFilterLogicKey: string
}

export type TaxonomicFilterValue = string | number

export interface TaxonomicFilterGroup {
    name: string
    searchPlaceholder: string
    type: TaxonomicFilterGroupType
    endpoint?: string
    /** If present, will be used instead of "endpoint" until the user presses "expand results". */
    scopedEndpoint?: string
    expandLabel?: (props: { count: number; expandedCount: number }) => React.ReactNode
    options?: Record<string, any>[]
    logic?: LogicWrapper
    value?: string
    searchAlias?: string
    valuesEndpoint?: (key: string) => string
    getName: (instance: any) => string
    getValue: (instance: any) => TaxonomicFilterValue
    getPopupHeader: (instance: any) => string
    getIcon?: (instance: any) => JSX.Element
    groupTypeIndex?: number
    getFullDetailUrl?: (instance: any) => string
}

export enum TaxonomicFilterGroupType {
    Actions = 'actions',
    Cohorts = 'cohorts',
    CohortsWithAllUsers = 'cohorts_with_all',
    Elements = 'elements',
    Events = 'events',
    EventProperties = 'event_properties',
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

export type TaxonomicDefinitionTypes = EventDefinition | PropertyDefinition | CohortType | ActionType | PersonProperty
