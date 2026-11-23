import { IconGear, IconRedo, IconUndo } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { useDashboardV2 } from '../dashboardV2Context'
import { TILE_SPACINGS, type TileSpacing } from '../layout/dashboardTypes'
import { AddTileMenu } from './AddTileMenu'

export function DashboardV2Actions(): JSX.Element {
    const { history, can, activeTab, dashboard, onEdit } = useDashboardV2()

    return (
        <div className="flex flex-wrap items-center gap-1">
            {can('addTile') && <AddTileMenu gridId={activeTab.id} label="Add" />}
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
            {can('setAppearance') && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                size="icon-sm"
                                aria-label="Customize"
                                tooltip="Customize"
                                data-attr="dashboard-v2-customize"
                            />
                        }
                    >
                        <IconGear />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Tile density</DropdownMenuLabel>
                            <DropdownMenuRadioGroup
                                value={dashboard.appearance?.tileSpacing ?? 'compact'}
                                onValueChange={(value) =>
                                    onEdit({
                                        edit: 'setAppearance',
                                        patch: { tileSpacing: value as TileSpacing },
                                    })
                                }
                            >
                                {(Object.keys(TILE_SPACINGS) as TileSpacing[]).map((spacing) => (
                                    <DropdownMenuRadioItem
                                        key={spacing}
                                        value={spacing}
                                        data-attr={`dashboard-v2-tile-density-${spacing}`}
                                    >
                                        {TILE_SPACINGS[spacing].label}
                                    </DropdownMenuRadioItem>
                                ))}
                            </DropdownMenuRadioGroup>
                        </DropdownMenuGroup>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </div>
    )
}
