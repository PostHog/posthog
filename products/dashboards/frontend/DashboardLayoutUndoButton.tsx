import { useActions, useValues } from 'kea'

import { IconUndo } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

const UNDO_TOOLTIP = (
    <span className="inline-flex items-center gap-1">
        Undo the last layout change
        <RenderKeybind keybind={[keyBinds.undo]} />
    </span>
)

export function DashboardLayoutUndoButton(): JSX.Element | null {
    const { canUndoLayoutChange, canEditLayout, undoLayoutDisabledReason } = useValues(dashboardLogic)
    const { undoLayoutChange } = useActions(dashboardLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!canUndoLayoutChange || !canEditLayout) {
        return null
    }

    const disabledReason = undoLayoutDisabledReason ?? undefined

    return todayRailNav ? (
        <Button
            variant="outline"
            data-attr="dashboard-layout-undo"
            onClick={undoLayoutChange}
            tooltip={UNDO_TOOLTIP}
            disabledReason={disabledReason}
        >
            <IconUndo />
            Undo
        </Button>
    ) : (
        <LemonButton
            type="secondary"
            size="small"
            data-attr="dashboard-layout-undo"
            icon={<IconUndo fontSize="16" />}
            onClick={undoLayoutChange}
            tooltip={UNDO_TOOLTIP}
            disabledReason={disabledReason}
        >
            Undo
        </LemonButton>
    )
}
