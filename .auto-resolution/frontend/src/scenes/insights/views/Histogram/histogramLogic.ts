import { actions, kea, path, reducers } from 'kea'

import { FunnelLayout } from 'lib/constants'
import { HistogramConfig, getConfig } from 'scenes/insights/views/Histogram/histogramUtils'

import type { histogramLogicType } from './histogramLogicType'

export const histogramLogic = kea<histogramLogicType>([
    path(['scenes', 'insights', 'Histogram', 'histogramLogic']),
    actions({
        setConfig: (config: HistogramConfig) => ({ config }),
    }),
    reducers({
        config: [
            getConfig(FunnelLayout.vertical),
            {
                setConfig: (state, { config }) => ({ ...state, ...config }),
            },
        ],
    }),
])
