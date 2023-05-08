import { kea, path, props, actions, selectors, listeners } from 'kea'
import { propertyFilterTypeToTaxonomicFilterType } from 'lib/components/PropertyFilters/utils'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { BreakdownFilter } from '~/queries/schema'
import { isCohortBreakdown, onFilterChange } from './taxonomicBreakdownFilterUtils'
import { ChartDisplayType, FilterType, PropertyDefinition, TrendsFilterType } from '~/types'

import type { taxonomicBreakdownFilterLogicType } from './taxonomicBreakdownFilterLogicType'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

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
        removeBreakdown: (breakdown: string | number) => ({ breakdown }),
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
        removeBreakdown: ({ breakdown }) => {
            if (!props.setFilters) {
                return
            }

            if (isCohortBreakdown(breakdown)) {
                const newParts = values.breakdownCohortArray.filter((cohort) => cohort !== breakdown)
                if (newParts.length === 0) {
                    props.setFilters({ breakdown: null, breakdown_type: null })
                } else {
                    props.setFilters({ breakdown: newParts, breakdown_type: 'cohort' })
                }
            } else {
                const newFilters: Partial<TrendsFilterType> = {
                    breakdown: undefined,
                    breakdown_type: undefined,
                    breakdown_histogram_bin_count: undefined,
                    // TODO: convert to data exploration
                    // Make sure we are no longer in map view after removing the Country Code breakdown
                    display:
                        isTrendsFilter(props.filters) && props.filters.display !== ChartDisplayType.WorldMap
                            ? props.filters.display
                            : undefined,
                }
                props.setFilters(newFilters)
            }
        },
    })),
])
