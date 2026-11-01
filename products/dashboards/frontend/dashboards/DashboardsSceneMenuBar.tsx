import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPencil, IconPlusSmall } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

import { SceneMenuBar, SceneMenuBarItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function DashboardsSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    return <DashboardsSceneMenuBarInner />
}

function DashboardsSceneMenuBarInner(): JSX.Element {
    const { showNewDashboardModal } = useActions(newDashboardLogic)
    const { searchParams } = useValues(router)
    const newDashboardDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Dashboard,
        AccessControlLevel.Editor
    )

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr="dashboards-menubar-file">
                <SceneMenuBarItem
                    data-attr="dashboards-menubar-new-dashboard"
                    opensFloatingUi
                    disabled={!!newDashboardDisabledReason}
                    tooltip={newDashboardDisabledReason ?? undefined}
                    onClick={showNewDashboardModal}
                >
                    <IconPlusSmall />
                    New dashboard
                </SceneMenuBarItem>
                <SceneMenuBarItem
                    data-attr="dashboards-menubar-manage-templates"
                    onClick={() => router.actions.push(combineUrl(urls.dashboardTemplates(), searchParams).url)}
                >
                    <IconPencil />
                    Manage templates
                </SceneMenuBarItem>
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
