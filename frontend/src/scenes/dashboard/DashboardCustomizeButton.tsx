import { useActions, useValues } from 'kea'

import { IconGridMasonry } from '@posthog/icons'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'

import { DashboardCustomizeMenu } from 'products/dashboards/frontend/components/DashboardCustomizeMenu/DashboardCustomizeMenu'

import { dashboardLogic } from './dashboardLogic'
import { QuillDashboardCustomizeButton } from './QuillDashboardCustomizeButton'

export function DashboardCustomizeButton(): JSX.Element {
    const { setDashboardEditing } = useActions(dashboardLogic)
    const { currentLayoutSize } = useValues(dashboardLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const layoutAvailable = currentLayoutSize !== 'xs'

    if (todayRailNav) {
        return <QuillDashboardCustomizeButton />
    }

    if (!layoutAvailable) {
        return (
            <LemonMenu
                items={[{ label: () => <DashboardCustomizeMenu /> }]}
                closeOnClickInside={false}
                placement="bottom-end"
            >
                <LemonButton
                    type="secondary"
                    data-attr="dashboard-edit-layout-customize-dropdown"
                    size="small"
                    icon={<IconGridMasonry fontSize="16" />}
                >
                    Customize
                </LemonButton>
            </LemonMenu>
        )
    }

    return (
        <Shortcut
            name="EnterEditMode"
            scope={Scene.Dashboard}
            keybind={[keyBinds.edit]}
            intent="Enter edit mode"
            interaction="click"
        >
            <LemonButton
                type="secondary"
                data-attr="dashboard-edit-mode-button"
                onClick={() =>
                    setDashboardEditing({ filters: true, layout: true }, DashboardEventSource.SceneCommonButtons)
                }
                size="small"
                icon={<IconGridMasonry fontSize="16" />}
                tooltip="Customize dashboard"
                tooltipPlacement="top"
                sideAction={{
                    'data-attr': 'dashboard-edit-layout-customize-dropdown',
                    dropdown: {
                        closeOnClickInside: false,
                        placement: 'bottom-end',
                        overlay: <LemonMenuOverlay items={[{ label: () => <DashboardCustomizeMenu /> }]} />,
                    },
                }}
            >
                Customize
            </LemonButton>
        </Shortcut>
    )
}
