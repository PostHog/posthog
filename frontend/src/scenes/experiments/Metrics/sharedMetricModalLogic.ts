import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { NodeKind } from '~/queries/schema/schema-general'

import { SharedMetric } from '../SharedMetrics/sharedMetricLogic'
import { sharedMetricsLogic } from '../SharedMetrics/sharedMetricsLogic'
import { METRIC_CONTEXTS, type MetricContext } from './experimentMetricModalLogic'
import type { sharedMetricModalLogicType } from './sharedMetricModalLogicType'

export const sharedMetricModalLogic = kea<sharedMetricModalLogicType>([
    path(['scenes', 'experiments', 'Metrics', 'sharedMetricModalLogic']),

    connect(() => ({
        actions: [sharedMetricsLogic, ['loadSharedMetrics'], eventUsageLogic, ['reportExperimentSharedMetricAssigned']],
        values: [sharedMetricsLogic, ['sharedMetrics', 'sharedMetricsLoading']],
    })),

    actions({
        openSharedMetricModal: (context: MetricContext, sharedMetricId?: SharedMetric['id'] | null) => ({
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
            METRIC_CONTEXTS.primary as MetricContext,
            {
                openSharedMetricModal: (_, { context }) => context,
                closeSharedMetricModal: () => METRIC_CONTEXTS.primary,
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
