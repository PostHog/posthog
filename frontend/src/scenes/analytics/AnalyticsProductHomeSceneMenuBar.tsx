import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { HomeDashboardMenu } from 'products/product_analytics/frontend/insights/home/HomeDashboardMenu'
import { useHomeDashboardActions } from 'products/product_analytics/frontend/insights/home/useHomeDashboardActions'

const RESOURCE_TYPE = 'analytics-home'

export function AnalyticsProductHomeSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <AnalyticsProductHomeSceneMenuBarInner />
}

function AnalyticsProductHomeSceneMenuBarInner(): JSX.Element {
    const homeDashboardActions = useHomeDashboardActions(RESOURCE_TYPE)

    const actions: SceneAction[] = homeDashboardActions.map((action) => ({
        ...action,
        pinned: { order: 0, variant: 'secondary', render: () => <HomeDashboardMenu /> },
    }))

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
