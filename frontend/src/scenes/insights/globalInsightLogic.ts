import { kea, path, actions, reducers } from 'kea'

import { FilterType } from '~/types'
import type { globalInsightLogicType } from './globalInsightLogicType'

export const FAST_MODE_DEFAULT_SAMPLING_RATE = 0.1

export const globalInsightLogic = kea<globalInsightLogicType>([
    path(['scenes', 'insights', 'globalInsightLogic']),
    actions(() => ({
        setGlobalInsightFilters: (globalInsightFilters: Partial<FilterType>) => ({ globalInsightFilters }),
    })),
    reducers(() => ({
        globalInsightFilters: [
            {} as Partial<FilterType>,
            {
                setGlobalInsightFilters: (_, { globalInsightFilters }) => globalInsightFilters,
            },
        ],
    })),
])
