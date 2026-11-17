import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconPencil, IconPlusSmall } from '@posthog/icons'

import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { DashboardsTab, dashboardsLogic } from 'scenes/dashboard/dashboards/dashboardsLogic'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { crossProjectDashboardsListLogic } from 'products/cross_project_dashboards/frontend/crossProjectDashboardsListLogic'
import { NewCrossProjectDashboardButton } from 'products/cross_project_dashboards/frontend/NewCrossProjectDashboardButton'

import { QuillDashboardsActions } from './QuillDashboardsActions'

const RESOURCE_TYPE = 'dashboards'

export function DashboardsSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTab } = useValues(dashboardsLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    // The cross-project list's logic loads on mount, so it mounts only while its tab is open, as the list does.
    const crossProjectTabOpen =
        !!featureFlags[FEATURE_FLAGS.CROSS_PROJECT_DASHBOARDS] && currentTab === DashboardsTab.CrossProject
    return crossProjectTabOpen ? (
        <DashboardsSceneMenuBarCrossProject />
    ) : (
        <DashboardsSceneMenuBarInner crossProjectActions={[]} />
    )
}

function DashboardsSceneMenuBarCrossProject(): JSX.Element {
    const { openNewModal } = useActions(crossProjectDashboardsListLogic)
    return (
        <DashboardsSceneMenuBarInner
            crossProjectActions={[
                {
                    group: 'file',
                    section: 'create',
                    id: `${RESOURCE_TYPE}-menubar-new-cross-project-dashboard`,
                    label: 'New cross-project dashboard',
                    icon: <IconPlusSmall />,
                    opensFloatingUi: true,
                    onSelect: openNewModal,
                    pinned: { order: 1, variant: 'primary', render: () => <NewCrossProjectDashboardButton /> },
                },
            ]}
        />
    )
}

function DashboardsSceneMenuBarInner({ crossProjectActions }: { crossProjectActions: SceneAction[] }): JSX.Element {
    const { showNewDashboardModal } = useActions(newDashboardLogic)
    const { searchParams } = useValues(router)
    const newDashboardDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Dashboard, AccessControlLevel.Editor) ?? undefined

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-dashboard`,
            label: 'New dashboard',
            icon: <IconPlusSmall />,
            opensFloatingUi: true,
            disabledReason: newDashboardDisabledReason,
            shortcut: <RenderKeybind keybind={[keyBinds.new]} minimal />,
            onSelect: showNewDashboardModal,
            pinned:
                crossProjectActions.length === 0
                    ? { order: 1, variant: 'primary', render: () => <QuillDashboardsActions /> }
                    : undefined,
        },
        ...crossProjectActions,
        {
            group: 'file',
            section: 'templates',
            id: `${RESOURCE_TYPE}-menubar-manage-templates`,
            label: 'Manage templates',
            icon: <IconPencil />,
            onSelect: () => router.actions.push(combineUrl(urls.dashboardTemplates(), searchParams).url),
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
