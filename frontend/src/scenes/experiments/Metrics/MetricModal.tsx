import { LemonButton, LemonDialog, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ExperimentFunnelsQuery } from '~/queries/schema'
import { Experiment, InsightType } from '~/types'

import { experimentLogic, getDefaultFunnelsMetric, getDefaultTrendsMetric } from '../experimentLogic'
import { FunnelsMetricForm } from './FunnelsMetricForm'
import { TrendsMetricForm } from './TrendsMetricForm'

export function MetricModal({
    experimentId,
    isSecondary,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
}): JSX.Element {
    const {
        experiment,
        experimentLoading,
        _getMetricType,
        isPrimaryMetricModalOpen,
        isSecondaryMetricModalOpen,
        editingPrimaryMetricIndex,
        editingSecondaryMetricIndex,
    } = useValues(experimentLogic({ experimentId }))
    const { updateExperimentGoal, setExperiment, closePrimaryMetricModal, closeSecondaryMetricModal } = useActions(
        experimentLogic({ experimentId })
    )

    const metricIdx = isSecondary ? editingSecondaryMetricIndex : editingPrimaryMetricIndex
    const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'

    if (!metricIdx && metricIdx !== 0) {
        return <></>
    }

    const metrics = experiment[metricsField]
    const metric = metrics[metricIdx]
    const metricType = _getMetricType(metric)
    const funnelStepsLength = (metric as ExperimentFunnelsQuery)?.funnels_query?.series?.length || 0

    return (
        <LemonModal
            isOpen={isSecondary ? isSecondaryMetricModalOpen : isPrimaryMetricModalOpen}
            onClose={isSecondary ? closeSecondaryMetricModal : closePrimaryMetricModal}
            width={1000}
            title="Edit experiment metric"
            footer={
                <div className="flex items-center w-full">
                    <LemonButton
                        type="secondary"
                        status="danger"
                        onClick={() => {
                            LemonDialog.open({
                                title: 'Delete this metric?',
                                content: <div className="text-sm text-muted">This action cannot be undone.</div>,
                                primaryButton: {
                                    children: 'Delete',
                                    type: 'primary',
                                    onClick: () => {
                                        const newMetrics = metrics.filter((_, idx) => idx !== metricIdx)
                                        setExperiment({
                                            [metricsField]: newMetrics,
                                        })
                                        updateExperimentGoal()
                                    },
                                    size: 'small',
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                    type: 'tertiary',
                                    size: 'small',
                                },
                            })
                        }}
                    >
                        Delete
                    </LemonButton>
                    <div className="flex items-center gap-2 ml-auto">
                        <LemonButton
                            form="edit-experiment-goal-form"
                            type="secondary"
                            onClick={isSecondary ? closeSecondaryMetricModal : closePrimaryMetricModal}
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
                        setExperiment({
                            ...experiment,
                            [metricsField]: [
                                ...metrics.slice(0, metricIdx),
                                newMetricType === InsightType.TRENDS
                                    ? getDefaultTrendsMetric()
                                    : getDefaultFunnelsMetric(),
                                ...metrics.slice(metricIdx + 1),
                            ],
                        })
                    }}
                    options={[
                        { value: InsightType.TRENDS, label: <b>Trends</b> },
                        { value: InsightType.FUNNELS, label: <b>Funnels</b> },
                    ]}
                />
            </div>
            {metricType === InsightType.TRENDS ? (
                <TrendsMetricForm isSecondary={isSecondary} />
            ) : (
                <FunnelsMetricForm isSecondary={isSecondary} />
            )}
        </LemonModal>
    )
}
