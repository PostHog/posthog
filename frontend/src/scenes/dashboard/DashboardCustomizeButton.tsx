import { useActions } from 'kea'

import { IconGridMasonry } from '@posthog/icons'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'
import { DashboardEventSource } from 'lib/utils/eventUsageLogic'
import { Scene } from 'scenes/sceneTypes'

import { DashboardCustomizeMenu } from 'products/dashboards/frontend/components/DashboardCustomizeMenu/DashboardCustomizeMenu'

import { dashboardLogic } from './dashboardLogic'

export function DashboardCustomizeButton(): JSX.Element {
    const { setDashboardEditing } = useActions(dashboardLogic)

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
