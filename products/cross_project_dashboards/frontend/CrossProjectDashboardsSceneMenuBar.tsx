import { useActions } from 'kea'

import { IconPlusSmall } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { crossProjectDashboardsListLogic } from './crossProjectDashboardsListLogic'

const RESOURCE_TYPE = 'cross-project-dashboards'

export function CrossProjectDashboardsSceneMenuBar(): JSX.Element | null {
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    if (!sceneMenuBarEnabled) {
        return null
    }
    return <CrossProjectDashboardsSceneMenuBarInner />
}

function CrossProjectDashboardsSceneMenuBarInner(): JSX.Element {
    const { openNewModal } = useActions(crossProjectDashboardsListLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new`,
            label: 'New cross-project dashboard',
            icon: <IconPlusSmall />,
            opensFloatingUi: true,
            onSelect: () => openNewModal(),
            // pinned: data-attr values are wire strings
            pinned: { order: 0, variant: 'primary', dataAttr: 'cross-project-dashboard-new' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
