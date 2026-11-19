import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { SceneMenuBar, SceneMenuBarItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'

import { dashboardV2ListLogic } from './dashboardV2ListLogic'

export function DashboardV2ListSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { setNewDialogOpen } = useActions(dashboardV2ListLogic)

    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr="dashboards-v2-menubar-file">
                <SceneMenuBarItem
                    opensFloatingUi
                    onClick={() => setNewDialogOpen(true)}
                    data-attr="dashboards-v2-menubar-new"
                >
                    <IconPlus />
                    New dashboard
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
