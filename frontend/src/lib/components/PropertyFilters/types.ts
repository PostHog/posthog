import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

import { AnyDataNode, DatabaseSchemaField } from '~/queries/schema'
import { AnyPropertyFilter, FilterLogicalOperator, PropertyGroupFilter } from '~/types'

export interface PropertyFilterBaseProps {
    pageKey: string
}

export interface PropertyFilterLogicProps extends PropertyFilterBaseProps {
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: AnyPropertyFilter[]) => void
    sendAllKeyUpdates?: boolean
}

export interface PropertyGroupFilterLogicProps extends PropertyFilterBaseProps {
    value?: PropertyGroupFilter
    onChange: (filters: PropertyGroupFilter) => void
}
export interface TaxonomicPropertyFilterLogicProps extends PropertyFilterBaseProps {
    propertyFilterLogic: ReturnType<typeof propertyFilterLogic.build>
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    taxonomicOnChange?: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue, item: any) => void
    filterIndex: number
    eventNames?: string[]
    propertyAllowList?: { [key in TaxonomicFilterGroupType]?: string[] }
}

export interface PropertyFilterInternalProps {
    pageKey?: string
    index: number
    onComplete: () => void
    disablePopover: boolean
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    taxonomicFilterOptionsFromProp?: TaxonomicFilterProps['optionsFromProp']
    eventNames?: string[]
    schemaColumns?: DatabaseSchemaField[]
    propertyGroupType?: FilterLogicalOperator | null
    orFiltering?: boolean
    addText?: string | null
    hasRowOperator?: boolean
    metadataSource?: AnyDataNode
    propertyAllowList?: { [key in TaxonomicFilterGroupType]?: string[] }
    allowRelativeDateOptions?: boolean
}
