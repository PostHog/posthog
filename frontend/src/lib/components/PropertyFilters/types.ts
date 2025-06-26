import {
    ExcludedProperties,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

import { AnyDataNode, DatabaseSchemaField } from '~/queries/schema/schema-general'
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
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    taxonomicOnChange?: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue, item: any) => void
    filters: AnyPropertyFilter[]
    setFilter: (index: number, property: AnyPropertyFilter) => void
    filterIndex: number
    eventNames?: string[]
    excludedProperties?: ExcludedProperties
    propertyAllowList?: { [key in TaxonomicFilterGroupType]?: string[] }
}

export interface PropertyFilterInternalProps {
    pageKey?: string
    index: number
    onComplete: () => void
    disablePopover: boolean
    filters: AnyPropertyFilter[]
    setFilter: (index: number, property: AnyPropertyFilter) => void
    editable?: boolean
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    taxonomicFilterOptionsFromProp?: TaxonomicFilterProps['optionsFromProp']
    eventNames?: string[]
    schemaColumns?: DatabaseSchemaField[]
    propertyGroupType?: FilterLogicalOperator | null
    orFiltering?: boolean
    addText?: string | null
    size?: 'xsmall' | 'small' | 'medium'
    hasRowOperator?: boolean
    metadataSource?: AnyDataNode
    propertyAllowList?: { [key in TaxonomicFilterGroupType]?: string[] }
    excludedProperties?: ExcludedProperties
    allowRelativeDateOptions?: boolean
    exactMatchFeatureFlagCohortOperators?: boolean
    hideBehavioralCohorts?: boolean
    addFilterDocLink?: string
}
