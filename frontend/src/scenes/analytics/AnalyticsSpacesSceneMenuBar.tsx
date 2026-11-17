import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { todayAnalyticsLogic } from 'products/today/frontend/analytics/todayAnalyticsLogic'

const RESOURCE_TYPE = 'analytics-spaces'

export function AnalyticsSpacesSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <AnalyticsSpacesSceneMenuBarInner />
}

function AnalyticsSpacesSceneMenuBarInner(): JSX.Element {
    const { setNewFolderDialogOpen } = useActions(todayAnalyticsLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-collection`,
            label: 'New collection',
            icon: <IconPlus />,
            opensFloatingUi: true,
            onSelect: () => setNewFolderDialogOpen(true),
            // pinned: data-attr values are wire strings
            pinned: { order: 0, variant: 'primary', dataAttr: 'analytics-spaces-new' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
