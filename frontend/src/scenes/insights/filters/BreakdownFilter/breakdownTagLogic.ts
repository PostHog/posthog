import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { FilterType, TrendsFilterType } from '~/types'

import type { breakdownTagLogicType } from './breakdownTagLogicType'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

export interface BreakdownTagLogicProps {
    setFilters?: (filters: Partial<FilterType>) => void
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
        setUseHistogram: ({ useHistogram }) => {
            const newFilter: TrendsFilterType = {
                breakdown_histogram_bin_count: useHistogram ? values.binCount : undefined,
            }
            props.setFilters?.(newFilter)
        },
        setBinCount: async ({ binCount }, breakpoint) => {
            await breakpoint(1000)
            const newFilter: TrendsFilterType = {
                breakdown_histogram_bin_count: values.useHistogram ? binCount : undefined,
            }
            props.setFilters?.(newFilter)
        },
    })),
])
