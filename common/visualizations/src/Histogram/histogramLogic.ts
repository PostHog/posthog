import { actions, kea, path, reducers } from 'kea'

import { FunnelLayout } from 'lib/constants'
// eslint-disable-next-line import/no-cycle
import { HistogramConfig, getConfig } from '@posthog/visualizations/Histogram/histogramUtils'

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
