import { IconGear } from '@posthog/icons'
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

import { useDashboardV2 } from '../dashboard/dashboardV2Context'
import { TILE_SPACINGS, type TileSpacing } from './tileSpacing'

export function TileSpacingMenu(): JSX.Element {
    const { dashboard, onEdit } = useDashboardV2()
    return (
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
                            onEdit({ edit: 'setAppearance', patch: { tileSpacing: value as TileSpacing } })
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
    )
}
