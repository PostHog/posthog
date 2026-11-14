import { ChartOptionSwitch } from 'lib/components/ChartOptions/ChartOptionSwitch'
import type { TileDisplayOptions } from 'scenes/dashboard/dashboardLogic'

import { DashboardTile } from '~/types'

export function TransparentBackgroundOption({
    tile,
    onUpdateDisplayOptions,
    saving,
    dataAttr,
}: {
    tile: DashboardTile
    onUpdateDisplayOptions: (displayOptions: TileDisplayOptions) => void
    saving?: boolean
    dataAttr: string
}): JSX.Element {
    return (
        <ChartOptionSwitch
            label="Transparent background"
            checked={!!tile.transparent_background}
            onChange={(checked) => onUpdateDisplayOptions({ transparent_background: checked })}
            disabledReason={saving ? 'Saving…' : null}
            data-attr={dataAttr}
        />
    )
}
