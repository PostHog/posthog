import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'

import { Experiment, InsightType } from '~/types'

import { experimentLogic, getDefaultFilters, getDefaultFunnelsMetric, getDefaultTrendsMetric } from '../experimentLogic'
import { SecondaryGoalFunnels } from './SecondaryGoalFunnels'
import { SecondaryGoalTrends } from './SecondaryGoalTrends'

export function SecondaryMetricModal({
    experimentId,
    metricIdx,
    isOpen,
    onClose,
}: {
    experimentId: Experiment['id']
    metricIdx: number
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const { experiment, experimentLoading, getSecondaryMetricType, featureFlags } = useValues(
        experimentLogic({ experimentId })
    )
    const { setExperiment, updateExperiment } = useActions(experimentLogic({ experimentId }))
    const metricType = getSecondaryMetricType(metricIdx)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1000}
            title="Change secondary metric"
            footer={
                <div className="flex items-center w-full">
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={() => {
                            // :FLAG: CLEAN UP AFTER MIGRATION
                            if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                                const newMetricsSecondary = experiment.metrics_secondary.filter(
                                    (_, idx) => idx !== metricIdx
                                )
                                setExperiment({
                                    metrics_secondary: newMetricsSecondary,
                                })
                                updateExperiment({
                                    metrics_secondary: newMetricsSecondary,
                                })
                            } else {
                                const newSecondaryMetrics = experiment.secondary_metrics.filter(
                                    (_, idx) => idx !== metricIdx
                                )
                                setExperiment({
                                    secondary_metrics: newSecondaryMetrics,
                                })
                                updateExperiment({
                                    secondary_metrics: newSecondaryMetrics,
                                })
                            }
                        }}
                    >
                        Delete
                    </LemonButton>
                    <div className="flex items-center gap-2 ml-auto">
                        <LemonButton type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            onClick={() => {
                                // :FLAG: CLEAN UP AFTER MIGRATION
                                if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                                    updateExperiment({
                                        metrics_secondary: experiment.metrics_secondary,
                                    })
                                } else {
                                    updateExperiment({
                                        secondary_metrics: experiment.secondary_metrics,
                                    })
                                }
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
                        // :FLAG: CLEAN UP AFTER MIGRATION
                        if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                            setExperiment({
                                ...experiment,
                                metrics_secondary: [
                                    ...experiment.metrics_secondary.slice(0, metricIdx),
                                    newMetricType === InsightType.TRENDS
                                        ? getDefaultTrendsMetric()
                                        : getDefaultFunnelsMetric(),
                                    ...experiment.metrics_secondary.slice(metricIdx + 1),
                                ],
                            })
                        } else {
                            setExperiment({
                                ...experiment,
                                secondary_metrics: [
                                    ...experiment.secondary_metrics.slice(0, metricIdx),
                                    newMetricType === InsightType.TRENDS
                                        ? { name: '', filters: getDefaultFilters(InsightType.TRENDS, undefined) }
                                        : { name: '', filters: getDefaultFilters(InsightType.FUNNELS, undefined) },
                                    ...experiment.secondary_metrics.slice(metricIdx + 1),
                                ],
                            })
                        }
                    }}
                    options={[
                        { value: InsightType.TRENDS, label: <b>Trends</b> },
                        { value: InsightType.FUNNELS, label: <b>Funnels</b> },
                    ]}
                />
            </div>
            {metricType === InsightType.TRENDS ? (
                <SecondaryGoalTrends metricIdx={metricIdx} />
            ) : (
                <SecondaryGoalFunnels metricIdx={metricIdx} />
            )}
        </LemonModal>
    )
}
