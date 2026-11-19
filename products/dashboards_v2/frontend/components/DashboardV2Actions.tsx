import { useActions, useValues } from 'kea'

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

import { dashboardV2Logic } from '../dashboardV2Logic'
import { TILE_SPACING_LABELS, type TileSpacing } from '../layout/dashboardTypes'
import { AddTileMenu } from './AddTileMenu'

export function DashboardV2Actions(): JSX.Element {
    const { canUndo, canRedo, canEditLayout, activeTab, dashboard } = useValues(dashboardV2Logic)
    const { undo, redo, applyDashboardEdit } = useActions(dashboardV2Logic)

    return (
        <div className="flex flex-wrap items-center gap-1">
            {canEditLayout && (
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
                                        applyDashboardEdit({
                                            edit: 'setAppearance',
                                            patch: { tileSpacing: value as TileSpacing },
                                        })
                                    }
                                >
                                    {(Object.keys(TILE_SPACING_LABELS) as TileSpacing[]).map((spacing) => (
                                        <DropdownMenuRadioItem
                                            key={spacing}
                                            value={spacing}
                                            data-attr={`dashboard-v2-tile-density-${spacing}`}
                                        >
                                            {TILE_SPACING_LABELS[spacing]}
                                        </DropdownMenuRadioItem>
                                    ))}
                                </DropdownMenuRadioGroup>
                            </DropdownMenuGroup>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </>
            )}
        </div>
    )
}
