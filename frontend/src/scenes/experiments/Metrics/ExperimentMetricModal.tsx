import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import type { ExperimentExposureCriteria, ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { ExperimentMetricForm } from '../ExperimentMetricForm'
import { exposureCriteriaModalLogic } from '../ExperimentView/exposureCriteriaModalLogic'
import { type MetricContext, experimentMetricModalLogic } from './experimentMetricModalLogic'

export function ExperimentMetricModal({
    experiment,
    exposureCriteria,
    onSave,
    onDelete,
}: {
    experiment: Experiment
    exposureCriteria: ExperimentExposureCriteria | undefined
    onSave: (metric: ExperimentMetric, context: MetricContext) => void | Promise<void>
    onDelete: (metric: ExperimentMetric, context: MetricContext) => void | Promise<void>
}): JSX.Element | null {
    const { isModalOpen, metric, context, isCreateMode, isEditMode } = useValues(experimentMetricModalLogic)
    const { closeExperimentMetricModal, setMetric: setModalMetric } = useActions(experimentMetricModalLogic)
    const { openExposureCriteriaModal } = useActions(exposureCriteriaModalLogic)
    const [isSaving, setIsSaving] = useState(false)

    if (!isModalOpen || !metric) {
        return null
    }

    const handleSave = async (): Promise<void> => {
        setIsSaving(true)
        try {
            await onSave(metric, context)
        } catch {
            // Failure is surfaced via a toast by the caller; keep the modal open to retry.
        } finally {
            setIsSaving(false)
        }
    }

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeExperimentMetricModal}
            title={isCreateMode ? 'Create experiment metric' : 'Edit experiment metric'}
            footer={
                <div className="flex items-center w-full">
                    {isEditMode && (
                        <LemonButton
                            type="secondary"
                            status="danger"
                            disabledReason={isSaving ? 'Saving…' : undefined}
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Delete this metric?',
                                    content: <div className="text-sm text-muted">This action cannot be undone.</div>,
                                    primaryButton: {
                                        children: 'Delete',
                                        type: 'primary',
                                        onClick: () => {
                                            // Toast + modal close handled by the caller.
                                            void Promise.resolve(onDelete(metric, context)).catch(() => {})
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
                    )}
                    <div className="flex items-center gap-2 ml-auto">
                        <LemonButton
                            form="edit-experiment-metric-form"
                            type="secondary"
                            disabledReason={isSaving ? 'Saving…' : undefined}
                            onClick={closeExperimentMetricModal}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="edit-experiment-metric-form"
                            onClick={handleSave}
                            loading={isSaving}
                            type="primary"
                            data-attr="save-experiment-metric"
                        >
                            {isCreateMode ? 'Create' : 'Save'}
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
                        setModalMetric({
                            ...metric,
                            name: newName,
                        })
                    }}
                />
            </div>
            <ExperimentMetricForm
                metric={metric}
                handleSetMetric={setModalMetric}
                filterTestAccounts={experiment.exposure_criteria?.filterTestAccounts || false}
                exposureCriteria={exposureCriteria}
                openExposureCriteriaModal={openExposureCriteriaModal}
            />
        </LemonModal>
    )
}
