import { useActions, useValues } from 'kea'

import { LemonButton, LemonInputSelect, LemonModal } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { InsightOption, addCrossProjectTileLogic } from './addCrossProjectTileLogic'

function InsightOptionLabel({ insight }: { insight: InsightOption }): JSX.Element {
    const detail = [insight.createdBy, insight.lastModifiedAt && `edited ${dayjs(insight.lastModifiedAt).fromNow()}`]
        .filter(Boolean)
        .join(' · ')
    return (
        <span className="flex items-center gap-2 w-full min-w-0">
            <span className="flex-1 truncate">{insight.name}</span>
            {detail ? <span className="shrink-0 text-xs text-secondary">{detail}</span> : null}
        </span>
    )
}

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

    const insightsByKey = new Map(
        [...insightPage.insights, ...(selectedInsight ? [selectedInsight] : [])].map((insight) => [
            String(insight.id),
            insight,
        ])
    )
    const loadMoreLabel =
        insightPage.total !== undefined
            ? `Load more insights (${insightPage.insights.length} of ${insightPage.total})`
            : 'Load more insights'

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
                    <LemonInputSelect
                        mode="single"
                        value={projectId ? [String(projectId)] : []}
                        onChange={(keys) => setProjectId(keys[0] ? Number(keys[0]) : null)}
                        options={projectOptions}
                        // An organization can pass the 100 options the plain list stops at.
                        virtualized
                        placeholder="Search projects"
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
                        options={insightOptions.map((option) => {
                            const insight = insightsByKey.get(option.key)
                            return insight
                                ? { ...option, labelComponent: <InsightOptionLabel insight={insight} /> }
                                : option
                        })}
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
                                      children: loadMoreLabel,
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
