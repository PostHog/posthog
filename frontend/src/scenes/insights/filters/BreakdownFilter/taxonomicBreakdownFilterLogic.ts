import { kea, path, props, actions, reducers, selectors, listeners, connect } from 'kea'
import { propertyFilterTypeToTaxonomicFilterType } from 'lib/components/PropertyFilters/utils'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { BreakdownFilter } from '~/queries/schema'
import { isCohortBreakdown, onFilterChange } from './taxonomicBreakdownFilterUtils'
import { ChartDisplayType, FilterType, TrendsFilterType } from '~/types'

import type { taxonomicBreakdownFilterLogicType } from './taxonomicBreakdownFilterLogicType'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

type TaxonomicBreakdownFilterLogicProps = {
    filters: BreakdownFilter
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
}

export const taxonomicBreakdownFilterLogic = kea<taxonomicBreakdownFilterLogicType>([
    path(['scenes', 'insights', 'filters', 'BreakdownFilter', 'taxonomicBreakdownFilterLogic']),
    props({} as TaxonomicBreakdownFilterLogicProps),
    connect(() => ({ values: [propertyDefinitionsModel, ['getPropertyDefinition']] })),
    actions({
        addBreakdown: (breakdown: TaxonomicFilterValue, taxonomicGroup: TaxonomicFilterGroup) => ({
            breakdown,
            taxonomicGroup,
        }),
        removeBreakdown: (breakdown: string | number) => ({ breakdown }),
        setHistogramBinsUsed: (value: boolean) => ({ value }),
        setHistogramBinCount: (count: number | undefined) => ({ count }),
        setNormalizeBreakdownURL: (normalizeBreakdownURL: boolean) => ({
            normalizeBreakdownURL,
        }),
    }),
    reducers(({ props }) => ({
        histogramBinsUsed: [
            props.filters && isTrendsFilter(props.filters) && props.filters.breakdown_histogram_bin_count !== undefined,
            {
                setHistogramBinsUsed: (_, { value }) => value,
            },
        ],
        histogramBinCount: [
            ((props.filters && isTrendsFilter(props.filters) && props.filters.breakdown_histogram_bin_count) ?? 10) as
                | number
                | undefined,
            {
                setHistogramBinCount: (_, { count }) => count,
            },
        ],
    })),
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
        isViewOnly: [(_, p) => [p.setFilters], (setFilters) => !setFilters],
    }),
    listeners(({ props, values }) => ({
        addBreakdown: ({ breakdown, taxonomicGroup }) => {
            if (!props.setFilters) {
                return
            }

            onFilterChange({
                breakdownCohortArray: values.breakdownCohortArray,
                setFilters: props.setFilters,
                getPropertyDefinition: values.getPropertyDefinition,
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
        setNormalizeBreakdownURL: ({ normalizeBreakdownURL }) => {
            const newFilter: TrendsFilterType = {
                breakdown_normalize_url: normalizeBreakdownURL,
            }
            props.setFilters?.(newFilter, true)
        },
        setHistogramBinsUsed: ({ value }) => {
            const newFilter: TrendsFilterType = {
                breakdown_histogram_bin_count: value ? values.histogramBinCount : undefined,
            }
            props.setFilters?.(newFilter, true)
        },
        setHistogramBinCount: async ({ count }, breakpoint) => {
            await breakpoint(1000)
            const newFilter: TrendsFilterType = {
                breakdown_histogram_bin_count: values.histogramBinsUsed ? count : undefined,
            }
            props.setFilters?.(newFilter, true)
        },
    })),
])
