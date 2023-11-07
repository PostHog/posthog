import { kea, path, actions, reducers } from 'kea'
import { getConfig, HistogramConfig } from 'scenes/insights/views/Histogram/histogramUtils'
import type { histogramLogicType } from './histogramLogicType'
import { FunnelLayout } from 'lib/constants'

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
