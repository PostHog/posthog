import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'

import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'

export function QuillCrossProjectDashboardRefreshAction(): JSX.Element | null {
    const { tiles, tilesRefreshing } = useValues(crossProjectDashboardLogic)
    const { refreshTiles } = useActions(crossProjectDashboardLogic)

    if (tiles.length === 0) {
        return null
    }

    return (
        <Shortcut
            name="CrossProjectDashboardRefresh"
            keybind={[keyBinds.refresh]}
            intent="Refresh dashboard"
            interaction="click"
        >
            <Button
                variant="outline"
                onClick={refreshTiles}
                loading={tilesRefreshing}
                data-attr="cross-project-dashboard-refresh"
                tooltip="Recalculate every tile instead of showing cached results"
            >
                <IconRefresh />
                Refresh
            </Button>
        </Shortcut>
    )
}
