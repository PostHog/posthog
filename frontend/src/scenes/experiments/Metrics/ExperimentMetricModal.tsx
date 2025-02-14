import { LemonButton, LemonDialog, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'

import { ExperimentMetric, ExperimentMetricType } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { ExperimentMetricForm } from './ExperimentMetricForm'

export function ExperimentMetricModal({
    experimentId,
    isSecondary,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
}): JSX.Element {
    const {
        experiment,
        experimentLoading,
        getExperimentMetricType,
        isPrimaryMetricModalOpen,
        isSecondaryMetricModalOpen,
        editingPrimaryMetricIndex,
        editingSecondaryMetricIndex,
    } = useValues(experimentLogic({ experimentId }))
    const {
        updateExperimentGoal,
        setExperiment,
        closePrimaryMetricModal,
        closeSecondaryMetricModal,
        restoreUnmodifiedExperiment,
    } = useActions(experimentLogic({ experimentId }))

    const metricIdx = isSecondary ? editingSecondaryMetricIndex : editingPrimaryMetricIndex
    const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'

    if (!metricIdx && metricIdx !== 0) {
        return <></>
    }

    const metrics = experiment[metricsField]
    const metric = metrics[metricIdx] as ExperimentMetric
    const metricType = getExperimentMetricType(metric)

    const onClose = (): void => {
        restoreUnmodifiedExperiment()
        isSecondary ? closeSecondaryMetricModal() : closePrimaryMetricModal()
    }

    return (
        <LemonModal
            isOpen={isSecondary ? isSecondaryMetricModalOpen : isPrimaryMetricModalOpen}
            onClose={onClose}
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
                                        isSecondary ? closeSecondaryMetricModal() : closePrimaryMetricModal()
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
                        <LemonButton form="edit-experiment-metric-form" type="secondary" onClick={onClose}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="edit-experiment-metric-form"
                            onClick={() => {
                                updateExperimentGoal()
                                isSecondary ? closeSecondaryMetricModal() : closePrimaryMetricModal()
                            }}
                            type="primary"
                            loading={experimentLoading}
                            data-attr="save-experiment-metric"
                        >
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="mb-4">
                <h4 className="mb-2">Metric type</h4>
                <LemonRadio
                    data-attr="metrics-selector"
                    value={metricType}
                    onChange={(newMetricType: ExperimentMetricType) => {
                        const newMetric = {
                            ...metrics[metricIdx],
                            metric_type: newMetricType,
                        }
                        setExperiment({
                            ...experiment,
                            [metricsField]: [
                                ...metrics.slice(0, metricIdx),
                                newMetric,
                                ...metrics.slice(metricIdx + 1),
                            ],
                        })
                    }}
                    options={[
                        { value: ExperimentMetricType.COUNT, label: 'Count' },
                        { value: ExperimentMetricType.CONTINUOUS, label: 'Continuous' },
                    ]}
                />
            </div>
            <ExperimentMetricForm isSecondary={isSecondary} />
        </LemonModal>
    )
}
