import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import type { TileDisplayOptions } from 'scenes/dashboard/dashboardLogic'

import { DashboardTile } from '~/types'

export function TextCardDisplayOptions({
    tile,
    onUpdateDisplayOptions,
}: {
    tile: DashboardTile
    onUpdateDisplayOptions: (displayOptions: TileDisplayOptions) => void
}): JSX.Element {
    return (
        <ChartOptionSwitch
            label="Transparent background"
            checked={!!tile.transparent_background}
            onChange={(checked) => onUpdateDisplayOptions({ transparent_background: checked })}
            data-attr="text-card-menu-transparent-background"
        />
    )
}
