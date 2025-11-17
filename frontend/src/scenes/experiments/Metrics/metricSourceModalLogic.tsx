import { kea } from 'kea'
import { actions, path, reducers } from 'kea'

import { METRIC_CONTEXTS, type MetricContext } from './experimentMetricModalLogic'
import type { metricSourceModalLogicType } from './metricSourceModalLogicType'

export const metricSourceModalLogic = kea<metricSourceModalLogicType>([
    path(['scenes', 'experiments', 'metrics', 'metricSourceModalLogic']),

    actions({
        openMetricSourceModal: (context: MetricContext) => ({ context }),
        closeMetricSourceModal: true,
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openMetricSourceModal: () => true,
                closeMetricSourceModal: () => false,
            },
        ],
        context: [
            METRIC_CONTEXTS.primary as MetricContext,
            {
                openMetricSourceModal: (_, { context }) => context,
                closeMetricSourceModal: () => METRIC_CONTEXTS.primary,
            },
        ],
    }),
])
