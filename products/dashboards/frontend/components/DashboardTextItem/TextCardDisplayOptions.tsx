import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import type { TileDisplayOptions } from 'scenes/dashboard/dashboardLogic'

import { DashboardTile } from '~/types'

export function TextCardDisplayOptions({
    tile,
    onUpdateDisplayOptions,
    saving,
}: {
    tile: DashboardTile
    onUpdateDisplayOptions: (displayOptions: TileDisplayOptions) => void
    saving?: boolean
}): JSX.Element {
    return (
        <ChartOptionSwitch
            label="Transparent background"
            checked={!!tile.transparent_background}
            onChange={(checked) => onUpdateDisplayOptions({ transparent_background: checked })}
            disabledReason={saving ? 'Saving…' : null}
            data-attr="text-card-menu-transparent-background"
        />
    )
}
