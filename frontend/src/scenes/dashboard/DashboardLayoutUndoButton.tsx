import { useActions, useValues } from 'kea'

import { IconUndo } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { dashboardLogic } from './dashboardLogic'

const UNDO_DISABLED_REASON = 'Wait for the dashboard to finish saving'

/** Layout changes save as they happen, so this is how an editor takes the last one back. */
export function DashboardLayoutUndoButton(): JSX.Element | null {
    const { canUndoLayoutChange, dashboardLoading } = useValues(dashboardLogic)
    const { undoLayoutChange } = useActions(dashboardLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!canUndoLayoutChange) {
        return null
    }

    const disabledReason = dashboardLoading ? UNDO_DISABLED_REASON : undefined

    return todayRailNav ? (
        <Button
            variant="outline"
            data-attr="dashboard-layout-undo"
            onClick={undoLayoutChange}
            tooltip="Undo the last layout change"
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
            tooltip="Undo the last layout change"
            disabledReason={disabledReason}
        >
            Undo
        </LemonButton>
    )
}
