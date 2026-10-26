import { useActions, useValues } from 'kea'

import { IconGridMasonry } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'

import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'

export function QuillCrossProjectDashboardLayoutActions(): JSX.Element | null {
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
                <Button
                    variant="outline"
                    data-attr="cross-project-dashboard-edit-mode-button"
                    onClick={enterLayoutEdit}
                    tooltip="Customize dashboard"
                >
                    <IconGridMasonry />
                    Customize
                </Button>
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
                <Button
                    data-attr="cross-project-dashboard-edit-mode-discard"
                    variant="outline"
                    onClick={cancelLayoutEdit}
                    tooltip="Discard layout changes and exit layout editing"
                >
                    Cancel
                </Button>
            </Shortcut>
            <Shortcut
                name="SaveCrossProjectDashboard"
                keybind={[keyBinds.edit, keyBinds.save]}
                intent="Save dashboard layout"
                interaction="click"
            >
                <Button
                    data-attr="cross-project-dashboard-edit-mode-save"
                    variant="primary"
                    onClick={saveLayout}
                    loading={layoutSaving}
                    tooltip="Save dashboard layout"
                    disabledReason={dashboardLoading ? 'Wait for dashboard to finish loading' : undefined}
                >
                    Save layout
                </Button>
            </Shortcut>
        </>
    )
}
