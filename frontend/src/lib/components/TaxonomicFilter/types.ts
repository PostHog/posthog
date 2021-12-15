import { LogicWrapper } from 'kea'
import { CohortType, EventDefinition } from '~/types'
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
}

export type TaxonomicFilterValue = string | number

export interface TaxonomicFilterLogicProps extends TaxonomicFilterProps {
    taxonomicFilterLogicKey: string
}

export interface TaxonomicFilterGroup {
    name: string
    searchPlaceholder: string
    type: TaxonomicFilterGroupType
    endpoint?: string
    options?: Record<string, any>[]
    logic?: LogicWrapper
    value?: string
    searchAlias?: string
    valuesEndpoint?: (key: string) => string
    getName: (instance: any) => string
    getValue: (instance: any) => TaxonomicFilterValue
    groupTypeIndex?: number
}

export enum TaxonomicFilterGroupType {
    Actions = 'actions',
    Cohorts = 'cohorts',
    CohortsWithAllUsers = 'cohorts_with_all',
    Elements = 'elements',
    Events = 'events',
    EventProperties = 'event_properties',
    PersonProperties = 'person_properties',
    PageviewUrls = 'pageview_urls',
    Screens = 'screens',
    CustomEvents = 'custom_events',
    Wildcards = 'wildcard',
    GroupsPrefix = 'groups',
}

export interface InfiniteListLogicProps extends TaxonomicFilterLogicProps {
    listGroupType: TaxonomicFilterGroupType
}

export interface ListStorage {
    results: (EventDefinition | CohortType)[]
    searchQuery?: string // Query used for the results currently in state
    count: number
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
