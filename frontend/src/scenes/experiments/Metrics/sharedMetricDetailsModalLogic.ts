import { actions, kea, path, reducers } from 'kea'

import type { ExperimentMetric } from '~/queries/schema/schema-general'

import { METRIC_CONTEXTS, type MetricContext } from './experimentMetricModalLogic'
import type { sharedMetricDetailsModalLogicType } from './sharedMetricDetailsModalLogicType'

export const sharedMetricDetailsModalLogic = kea<sharedMetricDetailsModalLogicType>([
    path(['scenes', 'experiments', 'Metrics', 'sharedMetricDetailsModalLogic']),

    actions({
        openSharedMetricDetailModal: (metric: ExperimentMetric, context: MetricContext) => ({
            metric,
            context,
        }),
        closeSharedMetricDetailModal: true,
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openSharedMetricDetailModal: () => true,
                closeSharedMetricDetailModal: () => false,
            },
        ],
        sharedMetric: [
            null as ExperimentMetric | null,
            {
                openSharedMetricDetailModal: (_, { metric }) => metric,
                closeSharedMetricDetailModal: () => null,
            },
        ],
        context: [
            METRIC_CONTEXTS.primary as MetricContext,
            {
                openSharedMetricDetailModal: (_, { context }) => context,
                closeSharedMetricDetailModal: () => METRIC_CONTEXTS.primary,
            },
        ],
    }),
])
