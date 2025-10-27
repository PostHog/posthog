import { actions, kea, path, reducers, selectors } from 'kea'

import type { ExperimentMetric } from '~/queries/schema/schema-general'

import { getDefaultFunnelMetric } from '../utils'
import type { experimentMetricModalLogicType } from './experimentMetricModalLogicType'

export const METRIC_CONTEXTS = {
    primary: {
        type: 'primary' as const,
        field: 'metrics' as const,
        orderingField: 'primary_metrics_ordered_uuids' as const,
    },
    secondary: {
        type: 'secondary' as const,
        field: 'metrics_secondary' as const,
        orderingField: 'secondary_metrics_ordered_uuids' as const,
    },
} as const

export type MetricContext = (typeof METRIC_CONTEXTS)[keyof typeof METRIC_CONTEXTS]

export const experimentMetricModalLogic = kea<experimentMetricModalLogicType>([
    path(['scenes', 'experiments', 'Metrics', 'experimentMetricModalLogic']),

    actions({
        openExperimentMetricModal: (context: MetricContext, metric?: ExperimentMetric) => ({ metric, context }),
        closeExperimentMetricModal: true,
        setMetric: (metric?: ExperimentMetric) => ({ metric }),
    }),

    reducers({
        isModalOpen: [
            false,
            {
                openExperimentMetricModal: () => true,
                closeExperimentMetricModal: () => false,
            },
        ],
        metric: [
            null as ExperimentMetric | null,
            {
                openExperimentMetricModal: (_, { metric }) => metric ?? getDefaultFunnelMetric(),
                closeExperimentMetricModal: () => null,
                setMetric: (_, { metric }) => metric ?? null,
            },
        ],
        context: [
            METRIC_CONTEXTS.primary as MetricContext,
            {
                openExperimentMetricModal: (_, { context }) => context,
                closeExperimentMetricModal: () => METRIC_CONTEXTS.primary,
            },
        ],
        isEditMode: [
            false,
            {
                openExperimentMetricModal: (_, { metric }) => !!metric,
                closeExperimentMetricModal: () => false,
            },
        ],
    }),

    selectors({
        isCreateMode: [(s) => [s.isEditMode], (isEditMode: boolean) => !isEditMode],
    }),
])
