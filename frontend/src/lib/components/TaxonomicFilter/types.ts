import { LogicWrapper } from 'kea'
import { PropertyFilterValue } from '~/types'

export interface TaxonomicFilterProps {
    groupType?: TaxonomicFilterGroupType
    value?: PropertyFilterValue
    onChange?: (groupType: TaxonomicFilterGroupType, value: PropertyFilterValue, item: any) => void
    onClose?: () => void
    groupTypes?: TaxonomicFilterGroupType[]
    taxonomicFilterLogicKey?: string
}

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
    getValue: (object: any) => PropertyFilterValue
}

export enum TaxonomicFilterGroupType {
    Actions = 'actions',
    Cohorts = 'cohorts',
    Elements = 'elements',
    Events = 'events',
    EventProperties = 'event_properties',
    PersonProperties = 'person_properties',
}

export interface InfiniteListLogicProps {
    taxonomicFilterLogicKey: string
    listGroupType: TaxonomicFilterGroupType
}
