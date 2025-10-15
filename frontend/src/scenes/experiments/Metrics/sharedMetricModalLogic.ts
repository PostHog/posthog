import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { NodeKind } from '~/queries/schema/schema-general'

import { SharedMetric } from '../SharedMetrics/sharedMetricLogic'
import { sharedMetricsLogic } from '../SharedMetrics/sharedMetricsLogic'
import type { MetricContext } from './experimentMetricModalLogic'
import type { sharedMetricModalLogicType } from './sharedMetricModalLogicType'

export const SHARED_METRIC_CONTEXTS = {
    primary: {
        type: 'primary' as const,
        field: 'shared_metrics' as const,
        orderingField: 'primary_metrics_ordered_uuids' as const,
    },
    secondary: {
        type: 'secondary' as const,
        field: 'shared_metrics_secondary' as const,
        orderingField: 'secondary_metrics_ordered_uuids' as const,
    },
} as const

export type SharedMetricContext = (typeof SHARED_METRIC_CONTEXTS)[keyof typeof SHARED_METRIC_CONTEXTS]

export const isSharedMetricContext = (context: MetricContext | SharedMetricContext): context is SharedMetricContext =>
    context.field === 'shared_metrics' || context.field === 'shared_metrics_secondary'

export const sharedMetricModalLogic = kea<sharedMetricModalLogicType>([
    path(['scenes', 'experiments', 'Metrics', 'sharedMetricModalLogic']),

    connect(() => ({
        actions: [sharedMetricsLogic, ['loadSharedMetrics'], eventUsageLogic, ['reportExperimentSharedMetricAssigned']],
        values: [sharedMetricsLogic, ['sharedMetrics', 'sharedMetricsLoading']],
    })),

    actions({
        openSharedMetricModal: (context: SharedMetricContext, sharedMetricId?: SharedMetric['id'] | null) => ({
            context,
            sharedMetricId,
        }),
        closeSharedMetricModal: true,
        setSharedMetric: (sharedMetric: SharedMetric) => ({ sharedMetric }),
    }),

    listeners(({ actions }) => ({
        openSharedMetricModal: () => {
            actions.loadSharedMetrics()
        },
    })),

    reducers({
        isModalOpen: [
            false,
            {
                openSharedMetricModal: () => true,
                closeSharedMetricModal: () => false,
            },
        ],
        sharedMetricId: [
            null as SharedMetric['id'] | null,
            {
                openSharedMetricModal: (_, { sharedMetricId }) => sharedMetricId ?? null,
                closeSharedMetricModal: () => null,
            },
        ],
        context: [
            SHARED_METRIC_CONTEXTS.primary as SharedMetricContext,
            {
                openSharedMetricModal: (_, { context }) => context,
                closeSharedMetricModal: () => SHARED_METRIC_CONTEXTS.primary,
            },
        ],
        isEditMode: [
            false,
            {
                openSharedMetricModal: (_, { sharedMetricId }) => !!sharedMetricId,
                closeSharedMetricModal: () => false,
            },
        ],
    }),

    selectors({
        isCreateMode: [(s) => [s.isEditMode], (isEditMode: boolean) => !isEditMode],
        compatibleSharedMetrics: [
            (s) => [s.sharedMetrics],
            (sharedMetrics: SharedMetric[]): SharedMetric[] => {
                return sharedMetrics.filter((metric) => metric.query.kind === NodeKind.ExperimentMetric)
            },
        ],
    }),
])
