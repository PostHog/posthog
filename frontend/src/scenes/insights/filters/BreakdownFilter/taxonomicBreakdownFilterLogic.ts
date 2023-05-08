import { kea, path, props, actions, selectors, listeners } from 'kea'
import { propertyFilterTypeToTaxonomicFilterType } from 'lib/components/PropertyFilters/utils'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { BreakdownFilter } from '~/queries/schema'
import { onFilterChange } from './taxonomicBreakdownFilterUtils'
import { FilterType, PropertyDefinition } from '~/types'

import type { taxonomicBreakdownFilterLogicType } from './taxonomicBreakdownFilterLogicType'

type TaxonomicBreakdownFilterLogicProps = {
    filters: BreakdownFilter
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
    getPropertyDefinition: (s: TaxonomicFilterValue) => PropertyDefinition | null
}

export const taxonomicBreakdownFilterLogic = kea<taxonomicBreakdownFilterLogicType>([
    path(['scenes', 'insights', 'filters', 'BreakdownFilter', 'taxonomicBreakdownFilterLogic']),
    props({} as TaxonomicBreakdownFilterLogicProps),
    actions({
        addBreakdown: (breakdown: TaxonomicFilterValue, taxonomicGroup: TaxonomicFilterGroup) => ({
            breakdown,
            taxonomicGroup,
        }),
    }),
    selectors({
        hasBreakdown: [(_, p) => [p.filters], ({ breakdown_type }) => !!breakdown_type],
        hasNonCohortBreakdown: [(_, p) => [p.filters], ({ breakdown }) => breakdown && typeof breakdown === 'string'],
        taxonomicBreakdownType: [
            (_, p) => [p.filters],
            ({ breakdown_type }) => {
                let breakdownType = propertyFilterTypeToTaxonomicFilterType(breakdown_type)
                if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
                    breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
                }
                return breakdownType
            },
        ],
        breakdownArray: [
            (_, p) => [p.filters],
            ({ breakdown }) =>
                (Array.isArray(breakdown) ? breakdown : [breakdown]).filter((b): b is string | number => !!b),
        ],
        breakdownCohortArray: [
            (s) => [s.breakdownArray],
            (breakdownArray) => breakdownArray.map((b) => (isNaN(Number(b)) ? b : Number(b))),
        ],
    }),
    listeners(({ props, values }) => ({
        addBreakdown: ({ breakdown, taxonomicGroup }) => {
            if (!props.setFilters) {
                return
            }

            onFilterChange({
                breakdownCohortArray: values.breakdownCohortArray,
                setFilters: props.setFilters,
                getPropertyDefinition: props.getPropertyDefinition,
            })(breakdown, taxonomicGroup)
        },
    })),
])
