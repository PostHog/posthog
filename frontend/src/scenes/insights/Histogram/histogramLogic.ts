import { kea } from 'kea'
import { getConfig, HistogramConfig } from 'scenes/insights/Histogram/histogramUtils'
import { histogramLogicType } from './histogramLogicType'
import { FunnelLayout } from 'lib/constants'

export const histogramLogic = kea<histogramLogicType>({
    actions: {
        setConfig: (config: HistogramConfig) => ({ config }),
    },
    reducers: {
        config: [
            getConfig(FunnelLayout.vertical),
            {
                setConfig: (state, { config }) => ({ ...state, ...config }),
            },
        ],
    },
})
