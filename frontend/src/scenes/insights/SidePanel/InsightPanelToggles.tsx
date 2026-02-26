import { useActions, useValues } from 'kea'

import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { ScenePanelActionsSection } from '~/layout/scenes/SceneLayout'
import { InsightLogicProps, ItemMode } from '~/types'

const RESOURCE_TYPE = 'insight'

export function InsightPanelToggles({ insightLogicProps }: { insightLogicProps: InsightLogicProps }): JSX.Element {
    const { insightMode } = useValues(insightSceneLogic)
    const { setInsightMode } = useActions(insightSceneLogic)

    const theInsightLogic = insightLogic(insightLogicProps)
    const { insightProps, insight, hasDashboardItemId } = useValues(theInsightLogic)

    const theInsightDataLogic = insightDataLogic(insightProps)
    const { showQueryEditor, showDebugPanel } = useValues(theInsightDataLogic)
    const { toggleQueryEditorPanel, toggleDebugPanel } = useActions(theInsightDataLogic)

    const { user } = useValues(userLogic)
    const { preflight } = useValues(preflightLogic)

    const isSavedInsight = hasDashboardItemId && !!insight?.id && !!insight?.short_id
    const canShowDebugPanel = isSavedInsight && (user?.is_staff || user?.is_impersonated || !preflight?.cloud)

    const handleToggleQueryEditorPanel = (): void => {
        if (hasDashboardItemId && insightMode !== ItemMode.Edit) {
            setInsightMode(ItemMode.Edit, null)

            if (showQueryEditor) {
                return
            }
        }

        toggleQueryEditorPanel()
    }

    return (
        <ScenePanelActionsSection>
            <LemonSwitch
                data-attr={`${RESOURCE_TYPE}-${showQueryEditor ? 'hide' : 'show'}-source`}
                className="px-2 py-1"
                checked={showQueryEditor}
                onChange={handleToggleQueryEditorPanel}
                fullWidth
                label="View source"
            />

            {canShowDebugPanel ? (
                <LemonSwitch
                    data-attr={`${RESOURCE_TYPE}-toggle-debug-panel`}
                    className="px-2 py-1"
                    checked={showDebugPanel}
                    onChange={toggleDebugPanel}
                    fullWidth
                    label="Debug panel"
                />
            ) : null}
        </ScenePanelActionsSection>
    )
}
