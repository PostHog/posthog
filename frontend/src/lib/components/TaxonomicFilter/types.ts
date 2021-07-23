import { LogicWrapper } from 'kea'

export interface TaxonomicFilterProps {
    groupType?: TaxonomicFilterGroupType
    value?: TaxonomicFilterValue
    onChange?: (groupType: TaxonomicFilterGroupType, value: TaxonomicFilterValue, item: any) => void
    onClose?: () => void
    groupTypes?: TaxonomicFilterGroupType[]
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
}

export enum TaxonomicFilterGroupType {
    Actions = 'actions',
    Cohorts = 'cohorts',
    CohortsWithAllUsers = 'cohorts_with_all',
    Elements = 'elements',
    Events = 'events',
    EventProperties = 'event_properties',
    PersonProperties = 'person_properties',
}

export interface InfiniteListLogicProps {
    taxonomicFilterLogicKey: string
    listGroupType: TaxonomicFilterGroupType
}
