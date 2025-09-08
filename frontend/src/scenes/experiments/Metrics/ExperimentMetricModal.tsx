import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import { ExperimentMetric } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { ExperimentMetricForm } from '../ExperimentMetricForm'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import { appendMetricToOrderingArray, removeMetricFromOrderingArray } from '../utils'

export function ExperimentMetricModal({
    experimentId,
    isSecondary,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
}): JSX.Element {
    const { experiment, experimentLoading, editingPrimaryMetricUuid, editingSecondaryMetricUuid } = useValues(
        experimentLogic({ experimentId })
    )
    const { setMetric, updateExperimentMetrics, setExperiment, restoreUnmodifiedExperiment } = useActions(
        experimentLogic({ experimentId })
    )
    const { closePrimaryMetricModal, closeSecondaryMetricModal } = useActions(modalsLogic)
    const { isPrimaryMetricModalOpen, isSecondaryMetricModalOpen } = useValues(modalsLogic)

    const metricUuid = isSecondary ? editingSecondaryMetricUuid : editingPrimaryMetricUuid
    const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'

    const handleSetMetric = useCallback(
        (newMetric: ExperimentMetric): void => {
            if (!metricUuid) {
                return
            }
            setMetric({ uuid: metricUuid, metric: newMetric, isSecondary })
        },
        [metricUuid, isSecondary, setMetric]
    )

    if (!metricUuid) {
        return <></>
    }

    const metrics = experiment[metricsField]
    const metric = metrics.find((m) => m.uuid === metricUuid) as ExperimentMetric

    if (!metric) {
        return <></>
    }

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
                                        const newOrderingArray = removeMetricFromOrderingArray(
                                            experiment,
                                            metricUuid,
                                            !!isSecondary
                                        )
                                        const newMetrics = metrics.filter((m) => m.uuid !== metricUuid)
                                        setExperiment({
                                            [metricsField]: newMetrics,
                                            [isSecondary
                                                ? 'secondary_metrics_ordered_uuids'
                                                : 'primary_metrics_ordered_uuids']: newOrderingArray,
                                        })
                                        updateExperimentMetrics()
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
                                const newOrderingArray = appendMetricToOrderingArray(
                                    experiment,
                                    metricUuid,
                                    !!isSecondary
                                )
                                setExperiment({
                                    [isSecondary ? 'secondary_metrics_ordered_uuids' : 'primary_metrics_ordered_uuids']:
                                        newOrderingArray,
                                })
                                updateExperimentMetrics()
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
                <LemonLabel className="mb-1">Name (optional)</LemonLabel>
                <LemonInput
                    value={metric.name}
                    onChange={(newName) => {
                        if (!metric.uuid) {
                            return
                        }
                        setMetric({
                            uuid: metric.uuid,
                            metric: {
                                ...metric,
                                name: newName,
                            },
                            isSecondary,
                        })
                    }}
                />
            </div>
            <ExperimentMetricForm
                metric={metric}
                handleSetMetric={handleSetMetric}
                filterTestAccounts={experiment.exposure_criteria?.filterTestAccounts || false}
            />
        </LemonModal>
    )
}
