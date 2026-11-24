import { useValues } from 'kea'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter } from '~/types'

import { FacetFilterBar } from './components/FacetFilterBar'
import { ALL_FACETS, FacetKey, nonFacetFilters, readFacets, withFacets, withNonFacetFilters } from './facetFilters'
import { facetOptionsLogic } from './facetOptionsLogic'

export interface ListFiltersHostProps {
    propertyFilters: AnyPropertyFilter[]
    onChange: (propertyFilters: AnyPropertyFilter[]) => void
    controls?: readonly FacetKey[]
    /** Defaults to event, person, group and cohort filters. */
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    pageKey: string
    'data-attr': string
}

/** The quick facets and the generic property filters, over one list of property filters. */
export function ListFiltersHost({
    propertyFilters,
    onChange,
    controls = ALL_FACETS,
    taxonomicGroupTypes,
    pageKey,
    'data-attr': dataAttr,
}: ListFiltersHostProps): JSX.Element {
    const { options } = useValues(facetOptionsLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    return (
        <>
            <FacetFilterBar
                facets={readFacets(propertyFilters)}
                options={options}
                controls={controls}
                onChange={(change) =>
                    onChange(withFacets(propertyFilters, change, options?.slowThresholdSeconds ?? null))
                }
                data-attr={dataAttr}
            />
            <PropertyFilters
                propertyFilters={nonFacetFilters(propertyFilters)}
                onChange={(pills) => onChange(withNonFacetFilters(propertyFilters, pills))}
                taxonomicGroupTypes={
                    taxonomicGroupTypes ?? [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ]
                }
                pageKey={pageKey}
            />
        </>
    )
}
