import { kea, path, props, defaults, actions, reducers, selectors, listeners, connect } from 'kea'
import {
    propertyFilterTypeToTaxonomicFilterType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { BreakdownFilter } from '~/queries/schema'
import { isCohortBreakdown, isURLNormalizeable } from './taxonomicBreakdownFilterUtils'
import { BreakdownType, ChartDisplayType, FilterType, TrendsFilterType } from '~/types'

import type { taxonomicBreakdownFilterLogicType } from './taxonomicBreakdownFilterLogicType'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

export type TaxonomicBreakdownFilterLogicProps = {
    breakdownFilter: BreakdownFilter
    setFilters: ((filters: Partial<FilterType>, mergeFilters?: boolean) => void) | null
}

export const taxonomicBreakdownFilterLogic = kea<taxonomicBreakdownFilterLogicType>([
    path(['scenes', 'insights', 'filters', 'BreakdownFilter', 'taxonomicBreakdownFilterLogic']),
    props({} as TaxonomicBreakdownFilterLogicProps),
    defaults({
        // This is a hack to get `TaxonomicFilterGroupType` imported in `taxonomicBreakdownFilterLogicType.ts`
        __ignore: null as TaxonomicFilterGroupType | null,
    }),
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
            props.breakdownFilter &&
                isTrendsFilter(props.breakdownFilter) &&
                props.breakdownFilter.breakdown_histogram_bin_count !== undefined,
            {
                setHistogramBinsUsed: (_, { value }) => value,
            },
        ],
        histogramBinCount: [
            ((props.breakdownFilter &&
                isTrendsFilter(props.breakdownFilter) &&
                props.breakdownFilter.breakdown_histogram_bin_count) ??
                10) as number | undefined,
            {
                setHistogramBinCount: (_, { count }) => count,
            },
        ],
    })),
    selectors({
        hasBreakdown: [(_, p) => [p.breakdownFilter], ({ breakdown_type }) => !!breakdown_type],
        hasNonCohortBreakdown: [
            (_, p) => [p.breakdownFilter],
            ({ breakdown }) => breakdown && typeof breakdown === 'string',
        ],
        taxonomicBreakdownType: [
            (_, p) => [p.breakdownFilter],
            ({ breakdown_type }) => {
                let breakdownType = propertyFilterTypeToTaxonomicFilterType(breakdown_type)
                if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
                    breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
                }
                return breakdownType
            },
        ],
        breakdownArray: [
            (_, p) => [p.breakdownFilter],
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
            const breakdownType = taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type) as BreakdownType
            const isHistogramable = !!values.getPropertyDefinition(breakdown)?.is_numerical

            if (!props.setFilters || !breakdownType) {
                return
            }

            const newFilters: Partial<TrendsFilterType> = {
                breakdown_type: breakdownType,
                breakdown:
                    taxonomicGroup.type === TaxonomicFilterGroupType.CohortsWithAllUsers
                        ? [...values.breakdownCohortArray, breakdown].filter((b): b is string | number => !!b)
                        : breakdown,
                breakdown_group_type_index: taxonomicGroup.groupTypeIndex,
                breakdown_histogram_bin_count: isHistogramable ? 10 : undefined,
                // If property definitions are not loaded when this runs then a normalizeable URL will not be normalized.
                // For now, it is safe to fall back to `breakdown` instead of the property definition.
                breakdown_normalize_url: isURLNormalizeable(
                    values.getPropertyDefinition(breakdown)?.name || (breakdown as string)
                ),
            }

            props.setFilters(newFilters, true)
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
                        isTrendsFilter(props.breakdownFilter) &&
                        props.breakdownFilter.display !== ChartDisplayType.WorldMap
                            ? props.breakdownFilter.display
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
