import { IconRedo, IconUndo } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AddTileMenu } from '../tiles/AddTileMenu'
import { AutoRefreshButton } from './AutoRefreshButton'
import { DashboardMenu } from './DashboardMenu'
import { useDashboardV2 } from './dashboardV2Context'

export function DashboardV2Actions(): JSX.Element {
    const { history, refresh, can, activeTab } = useDashboardV2()

    return (
        <div className="DashboardV2Actions flex flex-wrap items-center gap-1">
            {can('addTile') && <AddTileMenu gridId={activeTab.id} label="Add" />}
            {refresh && <AutoRefreshButton {...refresh} />}
            {history && can('undo') && (
                <>
                    <Button
                        size="icon-sm"
                        aria-label="Undo"
                        tooltip="Undo"
                        data-attr="dashboard-v2-undo"
                        disabledReason={history.canUndo ? undefined : 'Nothing to undo'}
                        onClick={history.onUndo}
                    >
                        <IconUndo />
                    </Button>
                    <Button
                        size="icon-sm"
                        aria-label="Redo"
                        tooltip="Redo"
                        data-attr="dashboard-v2-redo"
                        disabledReason={history.canRedo ? undefined : 'Nothing to redo'}
                        onClick={history.onRedo}
                    >
                        <IconRedo />
                    </Button>
                </>
            )}
            <DashboardMenu />
        </div>
    )
}
