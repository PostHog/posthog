import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'

import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'

/** Mirrors the single-project refresh button, which reads dashboardLogic, with its own data-attr to stay out of its analytics. */
export function CrossProjectDashboardRefreshAction(): JSX.Element | null {
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
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconRefresh />}
                onClick={refreshTiles}
                loading={tilesRefreshing}
                data-attr="cross-project-dashboard-refresh"
                tooltip="Recalculate every tile instead of showing cached results"
                tooltipPlacement="top"
            >
                Refresh
            </LemonButton>
        </Shortcut>
    )
}
