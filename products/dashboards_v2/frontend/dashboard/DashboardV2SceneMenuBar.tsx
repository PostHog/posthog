import { useActions, useValues } from 'kea'

import { IconCode, IconTrash } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'

import { dashboardV2Logic } from './dashboardV2Logic'

// pinned: prefix of this scene's menu bar data-attr values
const RESOURCE_TYPE = 'dashboard-v2'

export function DashboardV2SceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { spec } = useValues(dashboardV2Logic)
    const { openJsonDialog, setDeleteDialogOpen } = useActions(dashboardV2Logic)

    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR] || !spec) {
        return null
    }
    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${RESOURCE_TYPE}-menubar-file`}>
                <SceneMenuBarItem
                    opensFloatingUi
                    onClick={() => openJsonDialog()}
                    data-attr={`${RESOURCE_TYPE}-menubar-edit-json`}
                >
                    <IconCode />
                    Edit as JSON
                </SceneMenuBarItem>
                <SceneMenuBarSeparator />
                <SceneMenuBarItem
                    variant="destructive"
                    onClick={() => setDeleteDialogOpen(true)}
                    data-attr={`${RESOURCE_TYPE}-menubar-delete`}
                >
                    <IconTrash />
                    Delete dashboard
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
