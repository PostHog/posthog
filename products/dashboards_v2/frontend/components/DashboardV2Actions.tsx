import { useActions, useValues } from 'kea'

import { IconRedo, IconUndo } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { dashboardV2Logic } from '../dashboardV2Logic'
import { AddTileMenu } from './AddTileMenu'

export function DashboardV2Actions(): JSX.Element {
    const { canUndo, canRedo, hasPermission, activeTab } = useValues(dashboardV2Logic)
    const { undo, redo } = useActions(dashboardV2Logic)

    return (
        <div className="flex flex-wrap items-center gap-1">
            {hasPermission('addTile') && (
                <>
                    <AddTileMenu gridId={activeTab.id} label="Add" />
                    <Button
                        size="icon-sm"
                        aria-label="Undo"
                        tooltip="Undo"
                        data-attr="dashboard-v2-undo"
                        disabledReason={canUndo ? undefined : 'Nothing to undo'}
                        onClick={undo}
                    >
                        <IconUndo />
                    </Button>
                    <Button
                        size="icon-sm"
                        aria-label="Redo"
                        tooltip="Redo"
                        data-attr="dashboard-v2-redo"
                        disabledReason={canRedo ? undefined : 'Nothing to redo'}
                        onClick={redo}
                    >
                        <IconRedo />
                    </Button>
                </>
            )}
        </div>
    )
}
