import { useActions } from 'kea'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import { isExperimentMetric } from '~/queries/utils'
import { ExperimentMetricModal } from '~/scenes/experiments/Metrics/ExperimentMetricModal'
import { MetricSourceModal } from '~/scenes/experiments/Metrics/MetricSourceModal'
import { SharedMetricModal } from '~/scenes/experiments/Metrics/SharedMetricModal'
import {
    METRIC_CONTEXTS,
    MetricContext,
    experimentMetricModalLogic,
} from '~/scenes/experiments/Metrics/experimentMetricModalLogic'
import { sharedMetricModalLogic } from '~/scenes/experiments/Metrics/sharedMetricModalLogic'
import type { SharedMetric } from '~/scenes/experiments/SharedMetrics/sharedMetricLogic'
import type { Experiment } from '~/types'

import { EmptyMetricsPanel } from './EmptyMetricsPanel'
import { MetricList } from './MetricList'

export type MetricsPanelProps = {
    experiment: Experiment
    onSaveMetric: (metric: ExperimentMetric, context: MetricContext) => void
    onDeleteMetric: (metric: ExperimentMetric, context: MetricContext) => void
    onSaveSharedMetrics: (metrics: SharedMetric[], context: MetricContext) => void
    onDeleteSharedMetric: (metric: SharedMetric, context: MetricContext) => void
}

export const MetricsPanel = ({
    experiment,
    onSaveMetric,
    onDeleteMetric,
    onSaveSharedMetrics,
    onDeleteSharedMetric,
}: MetricsPanelProps): JSX.Element => {
    const { closeExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { closeSharedMetricModal } = useActions(sharedMetricModalLogic)

    // we need this value to calculate the recent activity on the metrics list
    const filterTestAccounts = experiment.filters?.filter_test_accounts || false

    const primaryMetrics = (experiment.metrics || []).filter(isExperimentMetric)
    const secondaryMetrics = (experiment.metrics_secondary || []).filter(isExperimentMetric)

    return (
        <div>
            {primaryMetrics.length > 0 ? (
                <MetricList
                    metrics={primaryMetrics}
                    metricContext={METRIC_CONTEXTS.primary}
                    onDelete={onDeleteMetric}
                    filterTestAccounts={filterTestAccounts}
                />
            ) : (
                <EmptyMetricsPanel metricContext={METRIC_CONTEXTS.primary} />
            )}

            {secondaryMetrics.length > 0 ? (
                <MetricList
                    metrics={secondaryMetrics}
                    metricContext={METRIC_CONTEXTS.secondary}
                    onDelete={onDeleteMetric}
                    filterTestAccounts={filterTestAccounts}
                    className="mt-6"
                />
            ) : (
                <EmptyMetricsPanel className="mt-6" metricContext={METRIC_CONTEXTS.secondary} />
            )}

            <MetricSourceModal />
            <ExperimentMetricModal
                experiment={experiment}
                onSave={(metric, context) => {
                    onSaveMetric(metric, context)
                    closeExperimentMetricModal()
                }}
                onDelete={(metric, context) => {
                    onDeleteMetric(metric, context)
                    closeExperimentMetricModal()
                }}
            />
            <SharedMetricModal
                experiment={experiment}
                onSave={(metrics, context) => {
                    onSaveSharedMetrics(metrics, context)
                    closeSharedMetricModal()
                }}
                onDelete={(metric, context) => {
                    onDeleteSharedMetric(metric, context)
                    closeSharedMetricModal()
                }}
            />
        </div>
    )
}
