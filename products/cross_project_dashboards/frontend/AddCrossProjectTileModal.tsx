import { useActions, useValues } from 'kea'

import { LemonButton, LemonInputSelect, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { addCrossProjectTileLogic } from './addCrossProjectTileLogic'

export interface AddCrossProjectTileModalProps {
    dashboardId: string
}

export function AddCrossProjectTileModal({ dashboardId }: AddCrossProjectTileModalProps): JSX.Element {
    const logic = addCrossProjectTileLogic({ dashboardId })
    const {
        isOpen,
        projectId,
        selectedInsight,
        projectOptions,
        insightPage,
        insightOptions,
        insightPageLoading,
        canAdd,
        isAdding,
    } = useValues(logic)
    const { closeModal, setProjectId, setInsight, setInsightSearch, loadMoreInsights, addTile } = useActions(logic)

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
                    <LemonInputSelect
                        mode="single"
                        value={selectedInsight ? [String(selectedInsight.id)] : []}
                        onChange={(keys) =>
                            setInsight(insightPage.insights.find((insight) => String(insight.id) === keys[0]) ?? null)
                        }
                        onInputChange={setInsightSearch}
                        options={insightOptions}
                        // The search runs on the server, so the list is already the answer to it.
                        disableFiltering
                        // Loaded pages can pass the 100 options the plain list stops at.
                        virtualized
                        placeholder={projectId ? 'Search insights' : 'Select a project first'}
                        disabledReason={!projectId ? 'Select a project first' : undefined}
                        loading={insightPageLoading}
                        action={
                            insightPage.hasMore
                                ? {
                                      children: 'Load more insights',
                                      onClick: loadMoreInsights,
                                      disabledReason: insightPageLoading ? 'Loading insights' : undefined,
                                  }
                                : undefined
                        }
                        data-attr="cross-project-add-tile-insight"
                        fullWidth
                    />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}
