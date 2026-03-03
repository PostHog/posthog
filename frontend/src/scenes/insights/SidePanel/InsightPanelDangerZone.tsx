import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { ScenePanelActionsSection, ScenePanelDivider } from '~/layout/scenes/SceneLayout'
import { AccessControlLevel, AccessControlResourceType, InsightLogicProps } from '~/types'

const RESOURCE_TYPE = 'insight'

export function InsightPanelDangerZone({
    insightLogicProps,
}: {
    insightLogicProps: InsightLogicProps
}): JSX.Element | null {
    const { dashboardId } = useValues(insightSceneLogic)

    const theInsightLogic = insightLogic(insightLogicProps)
    const { insight, hasDashboardItemId } = useValues(theInsightLogic)
    const { deleteInsight } = useActions(theInsightLogic)

    const isSavedInsight = hasDashboardItemId && !!insight?.id && !!insight?.short_id

    if (!isSavedInsight) {
        return null
    }

    return (
        <>
            <ScenePanelDivider />
            <ScenePanelActionsSection>
                <AccessControlAction
                    resourceType={AccessControlResourceType.Insight}
                    minAccessLevel={AccessControlLevel.Editor}
                >
                    {({ disabledReason }) => (
                        <ButtonPrimitive
                            menuItem
                            variant="danger"
                            disabled={!!disabledReason}
                            {...(disabledReason && { tooltip: disabledReason })}
                            data-attr={`${RESOURCE_TYPE}-delete`}
                            onClick={() => deleteInsight(dashboardId ?? null)}
                        >
                            <IconTrash />
                            Delete insight
                        </ButtonPrimitive>
                    )}
                </AccessControlAction>
            </ScenePanelActionsSection>
        </>
    )
}
