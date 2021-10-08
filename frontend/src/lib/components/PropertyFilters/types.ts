import { AnyPropertyFilter } from '~/types'

export interface PropertyFilterBaseProps {
    pageKey: string
}

export interface PropertyFilterLogicProps extends PropertyFilterBaseProps {
    propertyFilters?: AnyPropertyFilter[] | null
    onChange?: null | ((filters: AnyPropertyFilter[]) => void)
    urlOverride?: string
}

export interface TaxonomicPropertyFilterLogicProps extends PropertyFilterBaseProps {
    filterIndex: number
}
