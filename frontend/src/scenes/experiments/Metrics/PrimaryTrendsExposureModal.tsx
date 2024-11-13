import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'

import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { PrimaryGoalTrendsExposure } from '../Metrics/PrimaryGoalTrendsExposure'

export function PrimaryTrendsExposureModal({
    experimentId,
    isOpen,
    onClose,
}: {
    experimentId: Experiment['id']
    isOpen: boolean
    onClose: () => void
}): JSX.Element {
    const { experiment, experimentLoading, featureFlags } = useValues(experimentLogic({ experimentId }))
    const { updateExperimentExposure, updateExperiment } = useActions(experimentLogic({ experimentId }))

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            width={1000}
            title="Change experiment exposure"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton form="edit-experiment-exposure-form" type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => {
                            // :FLAG: CLEAN UP AFTER MIGRATION
                            if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_HOGQL]) {
                                updateExperiment({
                                    metrics: experiment.metrics,
                                })
                            } else {
                                updateExperimentExposure(experiment.parameters.custom_exposure_filter ?? null)
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
