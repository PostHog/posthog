import { AnyPropertyFilter } from '~/types'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

export interface PropertyFilterBaseProps {
    pageKey: string
}

export interface PropertyFilterLogicProps extends PropertyFilterBaseProps {
    propertyFilters?: AnyPropertyFilter[] | null
    onChange?: null | ((filters: AnyPropertyFilter[]) => void)
    urlOverride?: string
}

export interface TaxonomicPropertyFilterLogicProps extends PropertyFilterBaseProps {
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    taxonomicOnChange?: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue, item: any) => void
    filterIndex: number
}
