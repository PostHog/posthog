import { memo } from 'react'

import type { Tile } from '../layout/dashboardTypes'
import { ContentTile } from './ContentTile'
import { SectionTile } from './SectionTile'

export interface TileFrameProps {
    tile: Tile
    columnPx: number
    editable: boolean
    onSectionRows: (id: string, rows: number | null) => void
}

/** What a grid cell holds. Memoised on the tile, so a drag in a grid re-renders none of its tiles. */
export const TileFrame = memo(function TileFrame({
    tile,
    columnPx,
    editable,
    onSectionRows,
}: TileFrameProps): JSX.Element {
    const { id, widget } = tile
    if (widget.type !== 'section') {
        return <ContentTile id={id} widget={widget} editable={editable} />
    }
    return (
        <SectionTile
            id={id}
            widget={widget}
            columns={tile.place.w}
            columnPx={columnPx}
            editable={editable}
            onSectionRows={onSectionRows}
        />
    )
})
