import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { Experiment, InsightType } from '~/types'

import { experimentLogic, getDefaultFunnelsMetric, getDefaultTrendsMetric } from '../experimentLogic'
import { PrimaryGoalFunnels } from '../Metrics/PrimaryGoalFunnels'
import { PrimaryGoalTrends } from '../Metrics/PrimaryGoalTrends'

export function PrimaryMetricModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const {
        experiment,
        isExperimentGoalModalOpen,
        experimentLoading,
        getMetricType,
        trendMetricInsightLoading,
        funnelMetricInsightLoading,
    } = useValues(experimentLogic({ experimentId }))
    const { closeExperimentGoalModal, updateExperimentGoal, setExperiment } = useActions(
        experimentLogic({ experimentId })
    )

    const experimentFiltersLength =
        (experiment.filters?.events?.length || 0) + (experiment.filters?.actions?.length || 0)

    const metricIdx = 0
    const metricType = getMetricType(metricIdx)

    const isInsightLoading = metricType === InsightType.TRENDS ? trendMetricInsightLoading : funnelMetricInsightLoading

    return (
        <LemonModal
            isOpen={isExperimentGoalModalOpen}
            onClose={closeExperimentGoalModal}
            width={1000}
            title="Change experiment goal"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton form="edit-experiment-goal-form" type="secondary" onClick={closeExperimentGoalModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        disabledReason={
                            (isInsightLoading && 'The insight needs to be loaded before saving the goal.') ||
                            (metricType === InsightType.FUNNELS &&
                                experimentFiltersLength < 2 &&
                                'The experiment needs at least two funnel steps.')
                        }
                        form="edit-experiment-goal-form"
                        onClick={() => {
                            updateExperimentGoal(experiment.filters)
                        }}
                        type="primary"
                        loading={experimentLoading}
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="flex items-center w-full gap-2 mb-4">
                <span>Metric type</span>
                <LemonSelect
                    data-attr="metrics-selector"
                    value={metricType}
                    onChange={(newMetricType) => {
                        const defaultMetric =
                            newMetricType === InsightType.TRENDS ? getDefaultTrendsMetric() : getDefaultFunnelsMetric()

                        setExperiment({
                            ...experiment,
                            metrics: [
                                ...experiment.metrics.slice(0, metricIdx),
                                defaultMetric,
                                ...experiment.metrics.slice(metricIdx + 1),
                            ],
                        })
                    }}
                    options={[
                        { value: InsightType.TRENDS, label: <b>Trends</b> },
                        { value: InsightType.FUNNELS, label: <b>Funnels</b> },
                    ]}
                />
            </div>
            {metricType === InsightType.TRENDS ? <PrimaryGoalTrends /> : <PrimaryGoalFunnels />}
        </LemonModal>
    )
}
