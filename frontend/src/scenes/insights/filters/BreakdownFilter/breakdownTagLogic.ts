import { actions, kea, key, listeners, path, props, reducers } from 'kea'
import { FilterType } from '~/types'

import type { breakdownTagLogicType } from './breakdownTagLogicType'

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
            props.filters?.breakdown_histogram_bin_count !== undefined,
            {
                setUseHistogram: (_, { useHistogram }) => useHistogram,
            },
        ],
        binCount: [
            (props.filters?.breakdown_histogram_bin_count ?? 10) as number | undefined,
            {
                setBinCount: (_, { binCount }) => binCount,
            },
        ],
    })),
    listeners(({ props, values }) => ({
        setUseHistogram: ({ useHistogram }) => {
            props.setFilters?.({ breakdown_histogram_bin_count: useHistogram ? values.binCount : undefined })
        },
        setBinCount: ({ binCount }, breakpoint) => {
            breakpoint(1000)
            props.setFilters?.({ breakdown_histogram_bin_count: values.useHistogram ? binCount : undefined })
        },
    })),
])
