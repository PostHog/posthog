import { AnyPropertyFilter } from '~/types'
import { TaxonomicFilterGroupType, TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { SelectGradientOverflowProps } from 'lib/components/SelectGradientOverflow'

export interface PropertyFilterBaseProps {
    pageKey: string
}

export interface PropertyFilterLogicProps extends PropertyFilterBaseProps {
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: AnyPropertyFilter[]) => void
}

export interface TaxonomicPropertyFilterLogicProps {
    propertyFilterLogicProps: PropertyFilterLogicProps
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
    filterIndex: number
}

export interface PropertyFilterInternalProps {
    propertyFilterLogicProps: PropertyFilterLogicProps
    index: number
    selectProps: Partial<SelectGradientOverflowProps>
    onComplete: () => void
    disablePopover: boolean
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    eventNames?: string[]
}
