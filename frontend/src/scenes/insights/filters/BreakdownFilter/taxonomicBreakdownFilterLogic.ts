import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import {
    breakdownFilterToTaxonomicFilterType,
    propertyFilterTypeToPropertyDefinitionType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { Breakdown, BreakdownFilter } from '~/queries/schema/schema-general'
import { BreakdownType, ChartDisplayType, InsightLogicProps } from '~/types'

import type { taxonomicBreakdownFilterLogicType } from './taxonomicBreakdownFilterLogicType'
import { isCohortBreakdown, isMultipleBreakdownType, isURLNormalizeable } from './taxonomicBreakdownFilterUtils'

export type TaxonomicBreakdownFilterLogicProps = {
    insightProps: InsightLogicProps
    breakdownFilter: BreakdownFilter
    display?: ChartDisplayType | null
    isTrends: boolean
    updateBreakdownFilter: ((breakdownFilter: BreakdownFilter) => void) | null
    updateDisplay: ((display: ChartDisplayType | undefined) => void) | null
}

export const taxonomicBreakdownFilterLogic = kea<taxonomicBreakdownFilterLogicType>([
    props({} as TaxonomicBreakdownFilterLogicProps),
    key((props) => keyForInsightLogicProps('new')(props.insightProps)),
    path(['scenes', 'insights', 'filters', 'BreakdownFilter', 'taxonomicBreakdownFilterLogic']),
    defaults({
        // This is a hack to get `TaxonomicFilterGroupType` imported in `taxonomicBreakdownFilterLogicType.ts`
        __ignore: null as TaxonomicFilterGroupType | null,
    }),
    connect((props: TaxonomicBreakdownFilterLogicProps) => ({
        values: [
            insightVizDataLogic(props.insightProps),
            ['currentDataWarehouseSchemaColumns', 'hasDataWarehouseSeries'],
            propertyDefinitionsModel,
            ['getPropertyDefinition'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    actions({
        addBreakdown: (breakdown: TaxonomicFilterValue, taxonomicGroup: TaxonomicFilterGroup) => ({
            breakdown,
            taxonomicGroup,
        }),
        replaceBreakdown: (
            previousBreakdown: {
                value: string | number
                type: string
            },
            newBreakdown: {
                value: TaxonomicFilterValue
                group: TaxonomicFilterGroup
            }
        ) => ({
            previousBreakdown,
            newBreakdown,
        }),
        removeBreakdown: (breakdown: string | number, breakdownType: string) => ({ breakdown, breakdownType }),
        setBreakdownLimit: (value: number | undefined) => ({ value }),
        setHistogramBinsUsed: (
            breakdown: string | number,
            breakdownType: string,
            binsUsed: boolean,
            binCount?: number
        ) => ({
            binsUsed,
            binCount,
            breakdown,
            breakdownType,
        }),
        setHistogramBinCount: (breakdown: string | number, breakdownType: string, count: number | undefined) => ({
            breakdown,
            breakdownType,
            count,
        }),
        setNormalizeBreakdownURL: (
            breakdown: string | number,
            breakdownType: string,
            normalizeBreakdownURL: boolean
        ) => ({
            breakdown,
            breakdownType,
            normalizeBreakdownURL,
        }),
        toggleBreakdownOptions: (opened: boolean) => ({
            opened,
        }),
        setBreakdownHideOtherAggregation: (hidden: boolean) => ({
            hidden,
        }),
    }),
    reducers({
        localHistogramBinCount: [
            10 as number | undefined,
            {
                setHistogramBinCount: (_, { count }) => count,
            },
        ],
        localBreakdownLimit: [
            undefined as number | undefined,
            {
                setBreakdownLimit: (_, { value }) => value,
            },
        ],
        localNormalizeBreakdownURL: [
            true as boolean,
            {
                setNormalizeBreakdownURL: (_, { normalizeBreakdownURL }) => normalizeBreakdownURL,
            },
        ],
        localBreakdownHideOtherAggregation: [
            undefined as boolean | undefined,
            {
                setBreakdownHideOtherAggregation: (_, { hidden }) => hidden,
            },
        ],
        breakdownOptionsOpened: [
            false as boolean,
            {
                toggleBreakdownOptions: (_, { opened }) => opened,
            },
        ],
    }),
    selectors({
        isMultipleBreakdownsEnabled: [(_, p) => [p.isTrends], (isTrends) => isTrends],
        breakdownFilter: [(_, p) => [p.breakdownFilter], (breakdownFilter) => breakdownFilter],
        includeSessions: [(_, p) => [p.isTrends], (isTrends) => isTrends],
        isAddBreakdownDisabled: [
            (s) => [s.breakdownFilter, s.isMultipleBreakdownsEnabled, s.hasDataWarehouseSeries],
            ({ breakdown, breakdowns, breakdown_type }, isMultipleBreakdownsEnabled, hasDataWarehouseSeries) => {
                // Multiple breakdowns don't yet support the data warehouse, so it fallbacks to a single breakdown.
                if (
                    isMultipleBreakdownsEnabled &&
                    !hasDataWarehouseSeries &&
                    (!breakdown_type || isMultipleBreakdownType(breakdown_type))
                ) {
                    return !!breakdowns && breakdowns.length >= 3
                }

                return !Array.isArray(breakdown) && breakdown != null
            },
        ],
        taxonomicBreakdownType: [
            (s) => [s.breakdownFilter],
            (breakdownFilter) => {
                let breakdownType = breakdownFilterToTaxonomicFilterType(breakdownFilter)
                if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
                    breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
                }
                return breakdownType
            },
        ],
        breakdownArray: [
            (s) => [s.breakdownFilter, s.isMultipleBreakdownsEnabled],
            ({ breakdown, breakdowns }, isMultipleBreakdownsEnabled): (string | number)[] | Breakdown[] => {
                if (isMultipleBreakdownsEnabled && breakdowns) {
                    return breakdowns
                }

                return (Array.isArray(breakdown) ? breakdown : [breakdown]).filter((b): b is string | number => !!b)
            },
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
        breakdownLimit: [
            (s) => [s.breakdownFilter, s.localBreakdownLimit],
            (breakdownFilter, localBreakdownLimit) => localBreakdownLimit || breakdownFilter?.breakdown_limit || 25,
        ],
        normalizeBreakdownUrl: [
            (s) => [s.breakdownFilter, s.localNormalizeBreakdownURL],
            (breakdownFilter, localNormalizeBreakdownURL) =>
                localNormalizeBreakdownURL ?? breakdownFilter.breakdown_normalize_url ?? true,
        ],
        breakdownHideOtherAggregation: [
            (s) => [s.breakdownFilter, s.localBreakdownHideOtherAggregation],
            (breakdownFilter, localBreakdownHideOtherAggregation) =>
                localBreakdownHideOtherAggregation ?? breakdownFilter.breakdown_hide_other_aggregation,
        ],
    }),
    listeners(({ props, values, actions }) => ({
        addBreakdown: ({ breakdown, taxonomicGroup }) => {
            const breakdownType = taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type) as BreakdownType
            const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(breakdownType)
            const isHistogramable =
                !!values.getPropertyDefinition(breakdown, propertyDefinitionType)?.is_numerical && props.isTrends

            if (!props.updateBreakdownFilter || !breakdownType) {
                return
            }

            // If property definitions are not loaded when this runs then a normalizeable URL will not be normalized.
            // For now, it is safe to fall back to `breakdown` instead of the property definition.
            const isNormalizeable = isURLNormalizeable(
                values.getPropertyDefinition(breakdown, propertyDefinitionType)?.name || (breakdown as string)
            )

            const { breakdownFilter } = values

            // TODO: We're preventing duplicated cohorts with a Set. A better fix would be
            // to make excludedProperties work for cohorts in the TaxonomicFilter.
            const cohortBreakdown =
                breakdownFilter?.breakdown_type === 'cohort'
                    ? (Array.from(new Set([...values.breakdownCohortArray, breakdown])) as (string | number)[])
                    : ([breakdown] as (string | number)[])

            if (values.isMultipleBreakdownsEnabled && isMultipleBreakdownType(breakdownType)) {
                if (
                    checkBreakdownExists(breakdownFilter.breakdowns, breakdown, breakdownType) ||
                    (breakdownFilter.breakdown === breakdown && breakdownType === breakdownFilter.breakdown_type)
                ) {
                    return
                }

                const newBreakdown: Breakdown = {
                    property: breakdown as string,
                    type: breakdownType,
                    group_type_index: taxonomicGroup.groupTypeIndex,
                    histogram_bin_count: isHistogramable ? 10 : undefined,
                    normalize_url: isNormalizeable ? true : undefined,
                }

                const breakdowns = breakdownFilter.breakdowns
                    ? [...breakdownFilter.breakdowns, newBreakdown]
                    : [newBreakdown]

                // Keep backwards compatibility with old breakdowns. If there is a breakdown, convert it first to multiple breakdowns.
                if (isSingleBreakdown(breakdownFilter) && isMultipleBreakdownType(breakdownFilter.breakdown_type)) {
                    props.updateBreakdownFilter({
                        breakdown: undefined,
                        breakdown_type: undefined,
                        breakdown_histogram_bin_count: undefined,
                        breakdown_normalize_url: undefined,
                        breakdown_group_type_index: undefined,
                        breakdowns: [
                            {
                                property: breakdownFilter.breakdown as string,
                                type: breakdownFilter.breakdown_type,
                                group_type_index: breakdownFilter.breakdown_group_type_index,
                                histogram_bin_count: breakdownFilter.breakdown_histogram_bin_count,
                                normalize_url: breakdownFilter.breakdown_normalize_url,
                            },
                            ...breakdowns,
                        ],
                    })
                } else {
                    props.updateBreakdownFilter({
                        breakdown: undefined,
                        breakdown_type: undefined,
                        breakdown_histogram_bin_count: undefined,
                        breakdown_normalize_url: undefined,
                        breakdown_group_type_index: undefined,
                        breakdowns,
                    })
                }

                // Make sure we are no longer in map view after removing the Country Code breakdown
                if (
                    props.isTrends &&
                    props.display === ChartDisplayType.WorldMap &&
                    (breakdowns.length !== 1 || breakdowns[0].property !== '$geoip_country_code')
                ) {
                    props.updateDisplay?.(undefined)
                }
            } else {
                props.updateBreakdownFilter({
                    breakdowns: undefined,
                    breakdown_type: breakdownType,
                    breakdown:
                        taxonomicGroup.type === TaxonomicFilterGroupType.CohortsWithAllUsers
                            ? cohortBreakdown
                            : breakdown,
                    breakdown_group_type_index: taxonomicGroup.groupTypeIndex,
                    breakdown_histogram_bin_count: isHistogramable ? 10 : undefined,
                    breakdown_normalize_url: isNormalizeable ? true : undefined,
                })
            }
        },
        removeBreakdown: ({ breakdown, breakdownType }) => {
            if (!props.updateBreakdownFilter) {
                return
            }

            if (isCohortBreakdown(breakdown)) {
                const newParts = values.breakdownCohortArray.filter(
                    (cohort): cohort is string | number => cohort !== breakdown && typeof cohort !== 'object'
                )

                if (newParts.length === 0) {
                    props.updateBreakdownFilter({ ...props.breakdownFilter, breakdown: null, breakdown_type: null })
                } else {
                    props.updateBreakdownFilter({
                        ...props.breakdownFilter,
                        breakdown: newParts,
                        breakdown_type: 'cohort',
                    })
                }
            } else if (values.isMultipleBreakdownsEnabled) {
                const breakdowns = props.breakdownFilter.breakdowns?.filter(
                    (savedBreakdown) =>
                        !(savedBreakdown.property === breakdown && savedBreakdown.type === breakdownType)
                )

                props.updateBreakdownFilter({
                    ...props.breakdownFilter,
                    breakdown: undefined,
                    breakdown_type: undefined,
                    breakdown_histogram_bin_count: undefined,
                    breakdowns: breakdowns && breakdowns.length === 0 ? undefined : breakdowns,
                })

                // Make sure we are no longer in map view after removing the Country Code breakdown
                if (
                    (!breakdowns || breakdowns.length === 0) &&
                    props.isTrends &&
                    props.display === ChartDisplayType.WorldMap
                ) {
                    props.updateDisplay?.(undefined)
                }
            } else {
                props.updateBreakdownFilter({
                    ...props.breakdownFilter,
                    breakdowns: undefined,
                    breakdown: undefined,
                    breakdown_type: undefined,
                    breakdown_histogram_bin_count: undefined,
                })

                // Make sure we are no longer in map view after removing the Country Code breakdown
                if (props.isTrends && props.display === ChartDisplayType.WorldMap) {
                    props.updateDisplay?.(undefined)
                }
            }
        },
        replaceBreakdown: ({ previousBreakdown, newBreakdown }) => {
            const breakdownType = taxonomicFilterTypeToPropertyFilterType(newBreakdown.group.type) as
                | BreakdownType
                | undefined
            const breakdownValue = newBreakdown.value

            const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(breakdownType)
            const isHistogramable =
                !!values.getPropertyDefinition(breakdownValue, propertyDefinitionType)?.is_numerical && props.isTrends

            if (
                !props.updateBreakdownFilter ||
                !breakdownType ||
                (breakdownType === previousBreakdown.type && breakdownValue === previousBreakdown.value) ||
                checkBreakdownExists(values.breakdownFilter.breakdowns, breakdownValue, breakdownType)
            ) {
                return
            }

            // If property definitions are not loaded when this runs then a normalizeable URL will not be normalized.
            // For now, it is safe to fall back to `breakdown` instead of the property definition.
            const isNormalizeable = isURLNormalizeable(
                values.getPropertyDefinition(breakdownValue, propertyDefinitionType)?.name || (breakdownValue as string)
            )

            if (
                values.isMultipleBreakdownsEnabled &&
                isMultipleBreakdownType(breakdownType) &&
                typeof breakdownValue === 'string'
            ) {
                // Backward compatibility. If there is a single breakdown, remove it.
                if (!values.breakdownFilter.breakdowns) {
                    props.updateBreakdownFilter?.({
                        breakdowns: [
                            {
                                property: breakdownValue,
                                type: breakdownType,
                                group_type_index: newBreakdown.group.groupTypeIndex,
                                histogram_bin_count: isHistogramable ? 10 : undefined,
                                normalize_url: isNormalizeable ? true : undefined,
                            },
                        ],
                        breakdown: undefined,
                        breakdown_type: undefined,
                        breakdown_histogram_bin_count: undefined,
                        breakdown_normalize_url: undefined,
                        breakdown_group_type_index: undefined,
                    })
                } else {
                    const breakdowns = values.breakdownFilter.breakdowns?.map((savedBreakdown) => {
                        if (
                            savedBreakdown.property === previousBreakdown.value &&
                            savedBreakdown.type === previousBreakdown.type
                        ) {
                            return {
                                ...savedBreakdown,
                                property: breakdownValue,
                                type: breakdownType,
                                group_type_index: newBreakdown.group.groupTypeIndex,
                                histogram_bin_count: isHistogramable
                                    ? savedBreakdown.histogram_bin_count || 10
                                    : undefined,
                                normalize_url: isNormalizeable ? savedBreakdown.normalize_url ?? true : undefined,
                            }
                        }

                        return savedBreakdown
                    })

                    props.updateBreakdownFilter?.({
                        breakdowns,
                    })
                }
            } else {
                actions.addBreakdown(newBreakdown.value, newBreakdown.group)
            }
        },
        setBreakdownLimit: async ({ value }, breakpoint) => {
            await breakpoint(300)

            props.updateBreakdownFilter?.({
                ...values.breakdownFilter,
                breakdown_limit: value,
            })
        },
        setNormalizeBreakdownURL: ({ normalizeBreakdownURL, breakdown, breakdownType }) => {
            if (values.isMultipleBreakdownsEnabled && !isSingleBreakdown(values.breakdownFilter)) {
                props.updateBreakdownFilter?.({
                    breakdown_normalize_url: undefined,
                    breakdowns: updateNestedBreakdown(
                        values.breakdownFilter.breakdowns,
                        {
                            normalize_url: normalizeBreakdownURL,
                        },
                        breakdown,
                        breakdownType
                    ),
                })
            } else {
                props.updateBreakdownFilter?.({
                    breakdown_normalize_url: normalizeBreakdownURL,
                })
            }
        },
        setHistogramBinsUsed: ({ binsUsed, binCount, breakdown, breakdownType }) => {
            if (values.isMultipleBreakdownsEnabled && !isSingleBreakdown(values.breakdownFilter)) {
                props.updateBreakdownFilter?.({
                    breakdown_histogram_bin_count: undefined,
                    breakdowns: updateNestedBreakdown(
                        values.breakdownFilter.breakdowns,
                        {
                            histogram_bin_count: binsUsed ? binCount : undefined,
                        },
                        breakdown,
                        breakdownType
                    ),
                })
            } else {
                props.updateBreakdownFilter?.({
                    breakdown_histogram_bin_count: binsUsed ? values.histogramBinCount : undefined,
                })
            }
        },
        setHistogramBinCount: async ({ count, breakdown, breakdownType }, breakpoint) => {
            await breakpoint(1000)

            if (values.isMultipleBreakdownsEnabled && !isSingleBreakdown(values.breakdownFilter)) {
                props.updateBreakdownFilter?.({
                    breakdown_histogram_bin_count: undefined,
                    breakdowns: updateNestedBreakdown(
                        values.breakdownFilter.breakdowns,
                        {
                            histogram_bin_count: count,
                        },
                        breakdown,
                        breakdownType
                    ),
                })
            } else {
                props.updateBreakdownFilter?.({
                    breakdown_histogram_bin_count: values.histogramBinsUsed ? count : undefined,
                })
            }
        },
        setBreakdownHideOtherAggregation: async ({ hidden }, breakpoint) => {
            await breakpoint(300)
            props.updateBreakdownFilter?.({
                breakdown_hide_other_aggregation: hidden,
            })
        },
    })),
])

function updateNestedBreakdown(
    breakdowns: Breakdown[] | undefined,
    breakdownUpdate: Partial<Breakdown>,
    lookupValue: string | number,
    lookupType: string
): Breakdown[] | undefined {
    return breakdowns?.map((savedBreakdown) =>
        savedBreakdown.property === lookupValue && savedBreakdown.type === lookupType
            ? {
                  ...savedBreakdown,
                  ...breakdownUpdate,
              }
            : savedBreakdown
    )
}

function checkBreakdownExists(
    breakdowns: Breakdown[] | undefined,
    lookupValue: string | number | null,
    lookupType: string
): boolean {
    return !!breakdowns?.find(
        (savedBreakdown) => savedBreakdown.property === lookupValue && savedBreakdown.type === lookupType
    )
}

export function isSingleBreakdown(breakdownFilter?: BreakdownFilter | null): boolean {
    return !!(breakdownFilter && breakdownFilter.breakdown_type && breakdownFilter.breakdown)
}
