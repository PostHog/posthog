import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { ExperimentMetricForm } from '../ExperimentMetricForm'
import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'
import '../utils'

export function ExperimentMetricModal({
    experimentId,
    isSecondary,
    onSave,
    onDelete,
    onClose,
}: {
    experimentId: Experiment['id']
    isSecondary?: boolean
    onSave: () => void
    onDelete: () => void
    onClose: () => void
}): JSX.Element | null {
    const { experiment, experimentLoading, editingPrimaryMetricUuid, editingSecondaryMetricUuid } = useValues(
        experimentLogic({ experimentId })
    )
    const { setMetric } = useActions(experimentLogic({ experimentId }))
    const {} = useActions(modalsLogic)
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
        return null
    }

    const metrics = experiment[metricsField]
    const metric = metrics.find((m) => m.uuid === metricUuid) as ExperimentMetric

    if (!metric) {
        return null
    }

    return (
        <LemonModal
            isOpen={isSecondary ? isSecondaryMetricModalOpen : isPrimaryMetricModalOpen}
            onClose={onClose}
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
                                    onClick: onDelete,
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
                            onClick={onSave}
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
