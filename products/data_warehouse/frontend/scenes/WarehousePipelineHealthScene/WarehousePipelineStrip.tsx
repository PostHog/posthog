import { useValues } from 'kea'

import { WarehouseStatStrip } from '../WarehouseConsole/WarehouseStatStrip'
import { WarehouseStatTile } from '../WarehouseConsole/WarehouseStatTile'
import { warehousePipelineHealthLogic } from './warehousePipelineHealthLogic'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

/** How many events, persons and source tables are in each landing state. */
export function WarehousePipelineStrip(): JSX.Element {
    const { tiles } = useValues(warehousePipelineHealthLogic)

    return (
        <WarehouseStatStrip>
            {tiles.map((tile) => (
                <WarehouseStatTile
                    key={tile.state}
                    label={tile.label}
                    value={tile.value}
                    detail={tile.detail}
                    note={tile.note}
                    tone={tile.state === 'failing' && tile.value !== '0' ? 'danger' : 'default'}
                    data-attr={`warehouse-pipeline-health-tile-${tile.state.replaceAll('_', '-')}`}
                />
            ))}
        </WarehouseStatStrip>
    )
}
