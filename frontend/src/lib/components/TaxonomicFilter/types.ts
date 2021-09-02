import { LogicWrapper } from 'kea'
import { CohortType, EventDefinition } from '~/types'
import Fuse from 'fuse.js'

export interface TaxonomicFilterProps {
    groupType?: TaxonomicFilterGroupType
    value?: TaxonomicFilterValue
    onChange?: (groupType: TaxonomicFilterGroupType, value: TaxonomicFilterValue, item: any) => void
    onClose?: () => void
    groupTypes?: TaxonomicFilterGroupType[]
    groupAnalytics?: boolean
    taxonomicFilterLogicKey?: string
}

export type TaxonomicFilterValue = string | number

export interface TaxonomicFilterLogicProps extends TaxonomicFilterProps {
    taxonomicFilterLogicKey: string
}

export interface TaxonomicFilterGroup {
    name: string
    type: TaxonomicFilterGroupType
    endpoint?: string
    options?: Record<string, any>[]
    logic?: LogicWrapper
    value?: string
    getName: (object: any) => string
    getValue: (object: any) => TaxonomicFilterValue
    groupAnalytics?: boolean
}

export enum TaxonomicFilterGroupType {
    Actions = 'actions',
    Cohorts = 'cohorts',
    CohortsWithAllUsers = 'cohorts_with_all',
    Elements = 'elements',
    Events = 'events',
    EventProperties = 'event_properties',
    PersonProperties = 'person_properties',
    Group0 = 'group::0',
    Group1 = 'group::1',
    Group2 = 'group::2',
    Group3 = 'group::3',
    Group4 = 'group::4',
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
