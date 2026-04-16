import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'
import { LemonButton } from '@posthog/lemon-ui'

import { experimentLogic } from '../experimentLogic'
import { ConclusionForm } from '../ExperimentView/components'
import { legacyExperimentModalsLogic } from './legacyExperimentModalsLogic'

/**
 * @deprecated
 * This modal is used to edit the conclusion of a legacy experiment.
 * For modern experiments, use the EditConclusionModal component.
 */
export function LegacyEditConclusionModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { updateExperiment, restoreUnmodifiedExperiment } = useActions(experimentLogic)
    const { closeEditConclusionModal } = useActions(legacyExperimentModalsLogic)
    const { isEditConclusionModalOpen } = useValues(legacyExperimentModalsLogic)

    return (
        <LemonModal
            isOpen={isEditConclusionModalOpen}
            onClose={closeEditConclusionModal}
            title="Edit conclusion"
            width={600}
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        type="secondary"
                        onClick={() => {
                            restoreUnmodifiedExperiment()
                            closeEditConclusionModal()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={() => {
                            updateExperiment({
                                conclusion: experiment.conclusion,
                                conclusion_comment: experiment.conclusion_comment,
                            })
                            closeEditConclusionModal()
                        }}
                        type="primary"
                        disabledReason={!experiment.conclusion && 'Select a conclusion'}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <ConclusionForm />
        </LemonModal>
    )
}
