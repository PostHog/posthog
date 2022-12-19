import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { FilterType, TrendsFilterType } from '~/types'

import type { breakdownTagLogicType } from './breakdownTagLogicType'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

export interface BreakdownTagLogicProps {
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
    logicKey?: string
    filters?: Partial<FilterType>
}

export const breakdownTagLogic = kea<breakdownTagLogicType>([
    props({} as BreakdownTagLogicProps),
    key(({ logicKey }) => logicKey || 'global'),
    path((key) => ['scenes', 'insights', 'BreakdownFilter', 'breakdownTagLogic', key]),
    actions(() => ({
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
    listeners(({ props, values }) => ({
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
