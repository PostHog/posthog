import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { ExperimentMetric } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { ExperimentMetricForm } from '../ExperimentMetricForm'

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
        isPrimaryMetricModalOpen,
        isSecondaryMetricModalOpen,
        editingPrimaryMetricIndex,
        editingSecondaryMetricIndex,
    } = useValues(experimentLogic({ experimentId }))
    const { setMetric, updateExperimentMetrics, setExperiment, closePrimaryMetricModal, closeSecondaryMetricModal } =
        useActions(experimentLogic({ experimentId }))

    const metricIdx = isSecondary ? editingSecondaryMetricIndex : editingPrimaryMetricIndex
    const metricsField = isSecondary ? 'metrics_secondary' : 'metrics'

    const metrics = experiment[metricsField]
    const originalMetric = metricIdx != null ? (metrics[metricIdx] as ExperimentMetric) : null

    // Local state for the entire metric - only updates global state on save
    const [localMetric, setLocalMetric] = useState<ExperimentMetric | null>(originalMetric)

    // Update local state when metric changes (e.g., switching between metrics)
    useEffect(() => {
        setLocalMetric(originalMetric)
    }, [originalMetric])

    const handleSetLocalMetric = useCallback((newMetric: ExperimentMetric): void => {
        setLocalMetric(newMetric)
    }, [])

    const handleNameChange = useCallback(
        (newName: string) => {
            if (!localMetric) {
                return
            }
            setLocalMetric({
                ...localMetric,
                name: newName,
            })
        },
        [localMetric]
    )

    const saveMetric = useCallback(() => {
        if (metricIdx == null || !localMetric) {
            return
        }
        setMetric({ metricIdx, metric: localMetric, isSecondary })
        updateExperimentMetrics()
        isSecondary ? closeSecondaryMetricModal() : closePrimaryMetricModal()
    }, [
        metricIdx,
        localMetric,
        isSecondary,
        setMetric,
        updateExperimentMetrics,
        closeSecondaryMetricModal,
        closePrimaryMetricModal,
    ])

    if (metricIdx == null || !localMetric) {
        return <></>
    }

    const onClose = (): void => {
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
                            onClick={saveMetric}
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
                <LemonInput value={localMetric.name || ''} onChange={handleNameChange} />
            </div>
            <ExperimentMetricForm
                metric={localMetric}
                handleSetMetric={handleSetLocalMetric}
                filterTestAccounts={experiment.exposure_criteria?.filterTestAccounts || false}
            />
        </LemonModal>
    )
}
