import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

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
    const { experiment, experimentLoading } = useValues(experimentLogic({ experimentId }))
    const { updateExperiment } = useActions(experimentLogic({ experimentId }))

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
                            updateExperiment({
                                metrics: experiment.metrics,
                            })
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
