import { useActions, useValues } from 'kea'

import { IconGridMasonry } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'

import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'

/** Mirrors the single-project buttons, which read dashboardLogic, with own data-attrs to stay out of their analytics. */
export function CrossProjectDashboardLayoutActions(): JSX.Element | null {
    const { layoutEditMode, layoutSaving, tiles, dashboardLoading } = useValues(crossProjectDashboardLogic)
    const { enterLayoutEdit, cancelLayoutEdit, saveLayout } = useActions(crossProjectDashboardLogic)

    if (!layoutEditMode) {
        return tiles.length > 0 ? (
            <Shortcut
                name="EnterCrossProjectDashboardEditMode"
                keybind={[keyBinds.edit]}
                intent="Enter edit mode"
                interaction="click"
            >
                <LemonButton
                    type="secondary"
                    data-attr="cross-project-dashboard-edit-mode-button"
                    onClick={enterLayoutEdit}
                    size="small"
                    icon={<IconGridMasonry fontSize="16" />}
                    tooltip="Customize dashboard"
                    tooltipPlacement="top"
                >
                    Customize
                </LemonButton>
            </Shortcut>
        ) : null
    }

    return (
        <>
            <Shortcut
                name="CancelCrossProjectDashboardEdit"
                keybind={[keyBinds.escape]}
                intent="Cancel edit mode"
                interaction="click"
            >
                <LemonButton
                    data-attr="cross-project-dashboard-edit-mode-discard"
                    type="secondary"
                    onClick={cancelLayoutEdit}
                    size="small"
                    tooltip="Discard layout changes and exit layout editing"
                >
                    Cancel
                </LemonButton>
            </Shortcut>
            <Shortcut
                name="SaveCrossProjectDashboard"
                keybind={[keyBinds.edit, keyBinds.save]}
                intent="Save dashboard layout"
                interaction="click"
            >
                <LemonButton
                    data-attr="cross-project-dashboard-edit-mode-save"
                    type="primary"
                    onClick={saveLayout}
                    loading={layoutSaving}
                    size="small"
                    tooltip="Save dashboard layout"
                    tooltipPlacement="bottom"
                    disabledReason={dashboardLoading ? 'Wait for dashboard to finish loading' : undefined}
                >
                    Save layout
                </LemonButton>
            </Shortcut>
        </>
    )
}
