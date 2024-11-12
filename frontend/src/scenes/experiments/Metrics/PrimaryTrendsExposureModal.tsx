import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { PrimaryGoalTrendsExposure } from '../Metrics/PrimaryGoalTrendsExposure'

export function PrimaryTrendsExposureModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, isExperimentExposureModalOpen, experimentLoading } = useValues(
        experimentLogic({ experimentId })
    )
    const { closeExperimentExposureModal, updateExperimentExposure } = useActions(experimentLogic({ experimentId }))

    return (
        <LemonModal
            isOpen={isExperimentExposureModalOpen}
            onClose={closeExperimentExposureModal}
            width={1000}
            title="Change experiment exposure"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        type="secondary"
                        onClick={closeExperimentExposureModal}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => {
                            if (experiment.parameters.custom_exposure_filter) {
                                updateExperimentExposure(experiment.parameters.custom_exposure_filter)
                            }
                        }}
                        type="primary"
                        loading={experimentLoading}
                        data-attr="create-annotation-submit"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <PrimaryGoalTrendsExposure />
        </LemonModal>
    )
}
