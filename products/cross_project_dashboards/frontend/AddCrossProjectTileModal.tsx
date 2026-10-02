import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { addCrossProjectTileLogic } from './addCrossProjectTileLogic'

export interface AddCrossProjectTileModalProps {
    dashboardId: string
}

export function AddCrossProjectTileModal({ dashboardId }: AddCrossProjectTileModalProps): JSX.Element {
    const logic = addCrossProjectTileLogic({ dashboardId })
    const { isOpen, projectId, insightId, projectOptions, insightOptions, insightsLoading, canAdd, isAdding } =
        useValues(logic)
    const { closeModal, setProjectId, setInsightId, addTile } = useActions(logic)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={closeModal}
            title="Add an insight"
            description="Pick a project, then an insight from it. The tile shows that project's data."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={addTile}
                        disabledReason={!canAdd ? 'Pick a project and an insight first' : undefined}
                        loading={isAdding}
                        data-attr="cross-project-add-tile-confirm"
                    >
                        Add to dashboard
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4 min-w-100">
                <LemonField.Pure label="Project">
                    <LemonSelect
                        value={projectId}
                        onChange={setProjectId}
                        options={projectOptions}
                        placeholder="Select a project"
                        data-attr="cross-project-add-tile-project"
                        fullWidth
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Insight">
                    <LemonSelect
                        value={insightId}
                        onChange={setInsightId}
                        options={insightOptions}
                        placeholder={projectId ? 'Select an insight' : 'Select a project first'}
                        disabledReason={!projectId ? 'Select a project first' : undefined}
                        loading={insightsLoading}
                        data-attr="cross-project-add-tile-insight"
                        fullWidth
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}
