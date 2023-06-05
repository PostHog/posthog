import { actions, connect, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'
import {
    propertyFilterTypeToPropertyDefinitionType,
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
import { BreakdownType, ChartDisplayType } from '~/types'

import type { taxonomicBreakdownFilterLogicType } from './taxonomicBreakdownFilterLogicType'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'

export type TaxonomicBreakdownFilterLogicProps = {
    breakdownFilter: BreakdownFilter
    display?: ChartDisplayType | null
    isTrends: boolean
    updateBreakdown: ((breakdown: BreakdownFilter) => void) | null
    updateDisplay: ((display: ChartDisplayType | undefined) => void) | null
    isDataExploration: boolean
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
    reducers({
        localHistogramBinCount: [
            10 as number | undefined,
            {
                setHistogramBinCount: (_, { count }) => count,
            },
        ],
    }),
    selectors({
        breakdownFilter: [(_, p) => [p.breakdownFilter], (breakdownFilter) => breakdownFilter],
        isViewOnly: [(_, p) => [p.updateBreakdown], (updateBreakdown) => !updateBreakdown],
        includeSessions: [(_, p) => [p.isTrends], (isTrends) => isTrends],
        hasBreakdown: [(s) => [s.breakdownFilter], ({ breakdown_type }) => !!breakdown_type],
        hasNonCohortBreakdown: [
            (s) => [s.breakdownFilter],
            ({ breakdown }) => breakdown && typeof breakdown === 'string',
        ],
        taxonomicBreakdownType: [
            (s) => [s.breakdownFilter],
            ({ breakdown_type }) => {
                let breakdownType = propertyFilterTypeToTaxonomicFilterType(breakdown_type)
                if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
                    breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
                }
                return breakdownType
            },
        ],
        breakdownArray: [
            (s) => [s.breakdownFilter],
            ({ breakdown }) =>
                (Array.isArray(breakdown) ? breakdown : [breakdown]).filter((b): b is string | number => !!b),
        ],
        breakdownCohortArray: [
            (s) => [s.breakdownArray],
            (breakdownArray) => breakdownArray.map((b) => (isNaN(Number(b)) ? b : Number(b))),
        ],
        histogramBinsUsed: [
            (s) => [s.breakdownFilter],
            ({ breakdown_histogram_bin_count }) => breakdown_histogram_bin_count !== undefined,
        ],
        histogramBinCount: [
            (s) => [s.breakdownFilter, s.localHistogramBinCount],
            (breakdownFilter, localHistogramBinCount) =>
                localHistogramBinCount || breakdownFilter?.breakdown_histogram_bin_count,
        ],
    }),
    listeners(({ props, values }) => ({
        addBreakdown: ({ breakdown, taxonomicGroup }) => {
            const breakdownType = taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type) as BreakdownType
            const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(breakdownType)
            const isHistogramable = !!values.getPropertyDefinition(breakdown, propertyDefinitionType)?.is_numerical

            if (!props.updateBreakdown || !breakdownType) {
                return
            }

            // If property definitions are not loaded when this runs then a normalizeable URL will not be normalized.
            // For now, it is safe to fall back to `breakdown` instead of the property definition.
            const isNormalizeable = isURLNormalizeable(
                values.getPropertyDefinition(breakdown, propertyDefinitionType)?.name || (breakdown as string)
            )

            props.updateBreakdown({
                breakdown_type: breakdownType,
                breakdown:
                    taxonomicGroup.type === TaxonomicFilterGroupType.CohortsWithAllUsers
                        ? // TODO: We're preventing duplicated cohorts with a Set. A better fix would be
                          // to make exlcudedProperties work for cohorts in the TaxonomicFilter.
                          Array.from(new Set([...values.breakdownCohortArray, breakdown])).filter(
                              (b): b is string | number => !!b
                          )
                        : breakdown,
                breakdown_group_type_index: taxonomicGroup.groupTypeIndex,
                breakdown_histogram_bin_count: isHistogramable ? 10 : undefined,
                breakdown_normalize_url: isNormalizeable ? true : undefined,
            })
        },
        removeBreakdown: ({ breakdown }) => {
            if (!props.updateBreakdown) {
                return
            }

            if (isCohortBreakdown(breakdown)) {
                const newParts = values.breakdownCohortArray.filter((cohort) => cohort !== breakdown)
                if (newParts.length === 0) {
                    props.updateBreakdown({ ...props.breakdownFilter, breakdown: null, breakdown_type: null })
                } else {
                    props.updateBreakdown({ ...props.breakdownFilter, breakdown: newParts, breakdown_type: 'cohort' })
                }
            } else {
                props.updateBreakdown({
                    ...props.breakdownFilter,
                    ...(!props.isDataExploration ? { display: undefined } : {}),
                    breakdown: undefined,
                    breakdown_type: undefined,
                    breakdown_histogram_bin_count: undefined,
                })

                // Make sure we are no longer in map view after removing the Country Code breakdown
                if (props.isDataExploration && props.isTrends && props.display === ChartDisplayType.WorldMap) {
                    props.updateDisplay?.(undefined)
                }
            }
        },
        setNormalizeBreakdownURL: ({ normalizeBreakdownURL }) => {
            props.updateBreakdown?.({
                breakdown_normalize_url: normalizeBreakdownURL,
            })
        },
        setHistogramBinsUsed: ({ value }) => {
            props.updateBreakdown?.({
                breakdown_histogram_bin_count: value ? values.histogramBinCount : undefined,
            })
        },
        setHistogramBinCount: async ({ count }, breakpoint) => {
            await breakpoint(1000)
            props.updateBreakdown?.({
                breakdown_histogram_bin_count: values.histogramBinsUsed ? count : undefined,
            })
        },
    })),
])
