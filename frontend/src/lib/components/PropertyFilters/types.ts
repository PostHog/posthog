import { PropertyGroupFilter, AnyPropertyFilter, FilterLogicalOperator, PropertyFilter } from '~/types'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { SelectGradientOverflowProps } from 'lib/components/SelectGradientOverflow'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'

export interface PropertyFilterBaseProps {
    pageKey: string
}

export interface PropertyFilterLogicProps extends PropertyFilterBaseProps {
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: PropertyFilter[]) => void
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
}

export interface PropertyFilterInternalProps {
    pageKey?: string
    index: number
    selectProps: Partial<SelectGradientOverflowProps>
    onComplete: () => void
    disablePopover: boolean
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    eventNames?: string[]
    propertyGroupType?: FilterLogicalOperator | null
    orFiltering?: boolean
}
