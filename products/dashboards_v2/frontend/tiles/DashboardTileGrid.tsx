import './DashboardTileGrid.css'

import clsx from 'clsx'
import { type ComponentProps, memo, useCallback, useContext, useRef } from 'react'

import { type Tile, type TilePlace, isSectionWidget } from '../dashboard/dashboardTypes'
import { useDashboardV2 } from '../dashboard/dashboardV2Context'
import { findTile } from '../dashboard/tileTree'
import type { DropTarget } from '../grid/dropTargets'
import { type OnSectionRows, TileGrid } from '../grid/TileGrid'
import { CapturingTileContext, TileMountContext, useTileMounted } from '../grid/tileMounting'
import { ContentTile } from './ContentTile'
import { type SectionGridProps, SectionTile } from './SectionTile'

/**
 * A content tile whose card mounts only near the scrolled view. The sentinel fills the cell, so the cell is observed
 * whether the card or the placeholder is showing.
 */
function WindowedContentTile({ id, widget, editable }: ComponentProps<typeof ContentTile>): JSX.Element {
    const sentinel = useRef<HTMLSpanElement>(null)
    const mounted = useTileMounted(sentinel)
    return (
        <>
            <span ref={sentinel} aria-hidden className="DashboardTileGrid__sentinel" />
            {mounted ? (
                <ContentTile id={id} widget={widget} editable={editable} />
            ) : (
                <div className={clsx('DashboardTileGrid__placeholder', editable && 'TileGrid__handle')} />
            )}
        </>
    )
}

interface TileFrameProps {
    tile: Tile
    columnPx: number
    editable: boolean
    onSectionRows: OnSectionRows
}

/** What a grid cell holds. Memoised on the tile, so a drag in a grid re-renders none of its tiles. */
const TileFrame = memo(function TileFrame({ tile, columnPx, editable, onSectionRows }: TileFrameProps): JSX.Element {
    const { id, widget } = tile
    const capturing = useContext(CapturingTileContext) === id
    const content = isSectionWidget(widget) ? (
        <SectionTile
            id={id}
            widget={widget}
            columns={tile.place.w}
            columnPx={columnPx}
            editable={editable}
            onSectionRows={onSectionRows}
            renderGrid={renderSectionGrid}
        />
    ) : (
        <WindowedContentTile id={id} widget={widget} editable={editable} />
    )
    return capturing ? <TileMountContext.Provider value={null}>{content}</TileMountContext.Provider> : content
})

function renderSectionGrid(props: SectionGridProps): JSX.Element {
    return <DashboardTileGrid {...props} />
}

/** A grid of the dashboard's tiles, wired to the dashboard it sits in. */
export function DashboardTileGrid({
    gridId,
    tiles,
    cols,
    width,
    editable,
    onLiveRows,
}: Omit<SectionGridProps, 'onLiveRows'> & Partial<Pick<SectionGridProps, 'onLiveRows'>>): JSX.Element {
    const { dashboard, onEdit, sizeOf, can } = useDashboardV2()
    const renderTile = useCallback(
        (tile: Tile, columnPx: number, onSectionRows: OnSectionRows) => (
            <TileFrame tile={tile} columnPx={columnPx} editable={editable} onSectionRows={onSectionRows} />
        ),
        [editable]
    )
    const findCarried = useCallback((id: string) => findTile(dashboard, id), [dashboard])
    const onPlaceTiles = useCallback(
        (places: Record<string, TilePlace>, resized?: string) =>
            onEdit({ edit: 'placeTiles', grid: gridId, places, resized }),
        [onEdit, gridId]
    )
    const onMoveTile = useCallback(
        (id: string, target: DropTarget) =>
            onEdit({ edit: 'moveTile', id, grid: target.grid, x: target.x, y: target.y }),
        [onEdit]
    )
    return (
        <TileGrid
            gridId={gridId}
            tiles={tiles}
            cols={cols}
            width={width}
            editable={editable}
            sizeOf={sizeOf}
            renderTile={renderTile}
            findCarried={findCarried}
            onPlaceTiles={onPlaceTiles}
            onMoveTile={can('moveTile') ? onMoveTile : undefined}
            onLiveRows={onLiveRows}
        />
    )
}
