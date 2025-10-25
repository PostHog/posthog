import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonModal } from '@posthog/lemon-ui'

import type { ExperimentExposureCriteria, ExperimentMetric } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { ExperimentMetricForm } from '../ExperimentMetricForm'
import { modalsLogic } from '../modalsLogic'
import { type MetricContext, experimentMetricModalLogic } from './experimentMetricModalLogic'

export function ExperimentMetricModal({
    experiment,
    exposureCriteria,
    onSave,
    onDelete,
}: {
    experiment: Experiment
    exposureCriteria: ExperimentExposureCriteria | undefined
    onSave: (metric: ExperimentMetric, context: MetricContext) => void
    onDelete: (metric: ExperimentMetric, context: MetricContext) => void
}): JSX.Element | null {
    const { isModalOpen, metric, context, isCreateMode, isEditMode } = useValues(experimentMetricModalLogic)
    const { closeExperimentMetricModal, setMetric: setModalMetric } = useActions(experimentMetricModalLogic)
    const { openExposureCriteriaModal } = useActions(modalsLogic)

    if (!isModalOpen || !metric) {
        return null
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
                            onClick={() => {
                                LemonDialog.open({
                                    title: 'Delete this metric?',
                                    content: <div className="text-sm text-muted">This action cannot be undone.</div>,
                                    primaryButton: {
                                        children: 'Delete',
                                        type: 'primary',
                                        onClick: () => onDelete(metric, context),
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
                            onClick={closeExperimentMetricModal}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            form="edit-experiment-metric-form"
                            onClick={() => onSave(metric, context)}
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
