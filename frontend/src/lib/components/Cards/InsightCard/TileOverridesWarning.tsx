import { IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function TileOverridesWarning(): JSX.Element | null {
    return (
        <Tooltip
            title={
                <div className="flex items-center gap-1">
                    <span>Tile filters override all other filters</span>
                </div>
            }
        >
            <div className="flex items-center gap-1 text-warning">
                <IconWarning /> Tile filters applied
            </div>
        </Tooltip>
    )
}
