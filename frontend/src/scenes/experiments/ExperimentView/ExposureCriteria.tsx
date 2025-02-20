import { LemonButton } from '@posthog/lemon-ui'
import { LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { teamLogic } from 'scenes/teamLogic'

import { experimentLogic } from '../experimentLogic'

function ExposureCriteriaModal(): JSX.Element {
    const { experiment, isExposureCriteriaModalOpen } = useValues(experimentLogic)
    const { closeExposureCriteriaModal, restoreUnmodifiedExperiment, setExposureCriteria, updateExposureCriteria } =
        useActions(experimentLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    return (
        <LemonModal
            isOpen={isExposureCriteriaModalOpen}
            onClose={closeExposureCriteriaModal}
            width={550}
            title="Edit exposure criteria"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        type="secondary"
                        onClick={() => {
                            restoreUnmodifiedExperiment()
                            closeExposureCriteriaModal()
                        }}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        form="edit-experiment-exposure-form"
                        onClick={() => {
                            updateExposureCriteria()
                            closeExposureCriteriaModal()
                        }}
                        type="primary"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <TestAccountFilterSwitch
                checked={(() => {
                    const val = experiment.exposure_criteria?.filterTestAccounts
                    return hasFilters ? !!val : false
                })()}
                onChange={(checked: boolean) => {
                    setExposureCriteria({
                        filterTestAccounts: checked,
                    })
                }}
                fullWidth
            />
        </LemonModal>
    )
}

export function ExposureCriteria(): JSX.Element {
    const { openExposureCriteriaModal } = useActions(experimentLogic)
    return (
        <div>
            <h2 className="font-semibold text-lg mb-0">Exposure criteria</h2>
            <LemonButton className="mt-2" size="xsmall" type="secondary" onClick={() => openExposureCriteriaModal()}>
                Edit
            </LemonButton>
            <ExposureCriteriaModal />
        </div>
    )
}
