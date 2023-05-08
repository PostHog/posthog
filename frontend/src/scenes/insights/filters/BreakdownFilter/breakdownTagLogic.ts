import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { FilterType, TrendsFilterType } from '~/types'

import type { breakdownTagLogicType } from './breakdownTagLogicType'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'
import { isAllCohort, isCohort, isURLNormalizeable } from './taxonomicBreakdownFilterUtils'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { cohortsModel } from '~/models/cohortsModel'

export interface BreakdownTagLogicProps {
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
    breakdown: string | number
    filters?: Partial<FilterType>
}

export const breakdownTagLogic = kea<breakdownTagLogicType>([
    props({} as BreakdownTagLogicProps),
    key(({ breakdown }) => breakdown),
    path((key) => ['scenes', 'insights', 'BreakdownFilter', 'breakdownTagLogic', key]),
    connect(() => ({
        values: [
            taxonomicBreakdownFilterLogic,
            ['isViewOnly'],
            propertyDefinitionsModel,
            ['getPropertyDefinition'],
            cohortsModel,
            ['cohortsById'],
        ],
        actions: [taxonomicBreakdownFilterLogic, ['removeBreakdown as removeBreakdownFromList']],
    })),
    actions(() => ({
        removeBreakdown: true,
        setUseHistogram: (useHistogram: boolean) => ({ useHistogram }),
        setBinCount: (binCount: number | undefined) => ({ binCount }),
        setNormalizeBreakdownURL: (normalizeBreakdownURL: boolean) => ({
            normalizeBreakdownURL,
        }),
    })),
    reducers(({ props }) => ({
        useHistogram: [
            props.filters && isTrendsFilter(props.filters) && props.filters.breakdown_histogram_bin_count !== undefined,
            {
                setUseHistogram: (_, { useHistogram }) => useHistogram,
            },
        ],
        binCount: [
            ((props.filters && isTrendsFilter(props.filters) && props.filters.breakdown_histogram_bin_count) ?? 10) as
                | number
                | undefined,
            {
                setBinCount: (_, { binCount }) => binCount,
            },
        ],
    })),
    selectors({
        propertyDefinition: [
            (s, p) => [s.getPropertyDefinition, p.breakdown],
            (getPropertyDefinition, breakdown) => getPropertyDefinition(breakdown),
        ],
        propertyName: [
            (s, p) => [p.breakdown, s.cohortsById],
            (breakdown, cohortsById) => {
                if (isAllCohort(breakdown)) {
                    return 'All Users'
                } else if (isCohort(breakdown)) {
                    return cohortsById[breakdown]?.name || `Cohort ${breakdown}`
                } else {
                    // regular property breakdown i.e. person, event or group
                    return breakdown
                }
            },
        ],
        isHistogramable: [(s) => [s.propertyDefinition], (propertyDefinition) => !!propertyDefinition?.is_numerical],
        isNormalizeable: [
            (s) => [s.propertyDefinition],
            (propertyDefinition) => isURLNormalizeable(propertyDefinition?.name || ''),
        ],
        shouldShowMenu: [
            (s) => [s.isHistogramable, s.isNormalizeable],
            (isHistogramable, isNormalizeable) => isHistogramable || isNormalizeable,
        ],
    }),
    listeners(({ props, values, actions }) => ({
        removeBreakdown: () => {
            actions.removeBreakdownFromList(props.breakdown)
        },
        setNormalizeBreakdownURL: ({ normalizeBreakdownURL }) => {
            const newFilter: TrendsFilterType = {
                breakdown_normalize_url: normalizeBreakdownURL,
            }
            props.setFilters?.(newFilter, true)
        },
        setUseHistogram: ({ useHistogram }) => {
            const newFilter: TrendsFilterType = {
                breakdown_histogram_bin_count: useHistogram ? values.binCount : undefined,
            }
            props.setFilters?.(newFilter, true)
        },
        setBinCount: async ({ binCount }, breakpoint) => {
            await breakpoint(1000)
            const newFilter: TrendsFilterType = {
                breakdown_histogram_bin_count: values.useHistogram ? binCount : undefined,
            }
            props.setFilters?.(newFilter, true)
        },
    })),
])
