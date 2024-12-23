import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'

import { ExperimentFunnelsQuery } from '~/queries/schema'
import { Experiment, InsightType } from '~/types'

import { experimentLogic, getDefaultFilters, getDefaultFunnelsMetric, getDefaultTrendsMetric } from '../experimentLogic'
import { PrimaryGoalFunnels } from '../Metrics/PrimaryGoalFunnels'
import { PrimaryGoalTrends } from '../Metrics/PrimaryGoalTrends'

export function PrimaryMetricModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const {
        experiment,
        experimentLoading,
        getMetricType,
        featureFlags,
        isPrimaryMetricModalOpen,
        editingPrimaryMetricIndex,
    } = useValues(experimentLogic({ experimentId }))
    const { updateExperimentGoal, setExperiment, closePrimaryMetricModal } = useActions(
        experimentLogic({ experimentId })
    )

    if (!editingPrimaryMetricIndex && editingPrimaryMetricIndex !== 0) {
        return <></>
    }

    const metricIdx = editingPrimaryMetricIndex
    const metricType = getMetricType(metricIdx)

    let funnelStepsLength = 0
    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL] && metricType === InsightType.FUNNELS) {
        const metric = experiment.metrics[metricIdx] as ExperimentFunnelsQuery
        funnelStepsLength = metric?.funnels_query?.series?.length || 0
    } else {
        funnelStepsLength = (experiment.filters?.events?.length || 0) + (experiment.filters?.actions?.length || 0)
    }

    return (
        <LemonModal
            isOpen={isPrimaryMetricModalOpen}
            onClose={closePrimaryMetricModal}
            width={1000}
            title="Change experiment goal"
            footer={
                <div className="flex items-center w-full">
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={() => {
                            const newMetrics = experiment.metrics.filter((_, idx) => idx !== metricIdx)
                            setExperiment({
                                metrics: newMetrics,
                            })
                            updateExperimentGoal()
                        }}
                    >
                        Delete
                    </LemonButton>
                    <div className="flex items-center gap-2 ml-auto">
                        <LemonButton
                            form="edit-experiment-goal-form"
                            type="secondary"
                            onClick={closePrimaryMetricModal}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            disabledReason={
                                metricType === InsightType.FUNNELS &&
                                funnelStepsLength < 2 &&
                                'The experiment needs at least two funnel steps.'
                            }
                            form="edit-experiment-goal-form"
                            onClick={() => {
                                updateExperimentGoal()
                            }}
                            type="primary"
                            loading={experimentLoading}
                            data-attr="create-annotation-submit"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="flex items-center w-full gap-2 mb-4">
                <span>Metric type</span>
                <LemonSelect
                    data-attr="metrics-selector"
                    value={metricType}
                    onChange={(newMetricType) => {
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setExperiment({
                                ...experiment,
                                metrics: [
                                    ...experiment.metrics.slice(0, metricIdx),
                                    newMetricType === InsightType.TRENDS
                                        ? getDefaultTrendsMetric()
                                        : getDefaultFunnelsMetric(),
                                    ...experiment.metrics.slice(metricIdx + 1),
                                ],
                            })
                        } else {
                            setExperiment({
                                ...experiment,
                                filters: getDefaultFilters(newMetricType, undefined),
                            })
                        }
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
