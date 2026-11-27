import './DashboardTileGrid.css'

import { memo, useCallback, useContext, useRef } from 'react'

import type { DropTarget } from '../../grid/drag/dropTargets'
import { type OnSectionRows, TileGrid } from '../../grid/TileGrid'
import { CapturingTileContext, TileMountContext, useTileMounted } from '../../grid/tileMounting'
import type { PanelType } from '../../panels/core/panelDefinition'
import { type SavedPanel } from '../../panels/core/panelSchema'
import { findPanel } from '../../panels/core/panelSpec'
import { ContentTile } from '../../tiles/core/ContentTile'
import { ContentTilePlaceholder } from '../../tiles/core/ContentTilePlaceholder'
import { useContentTileActions, useContentTilePlacementActions } from '../../tiles/menu/tileMenuActions'
import { type SectionGridProps, SectionTile } from '../../tiles/SectionTile'
import { type Tile, type TilePlace, isSectionPanel } from '../document/dashboardTypes'
import { findTile } from '../document/tileTree'
import { useDashboard } from './dashboardContext'

type DashboardContentTileProps = {
    id: string
    panel: SavedPanel
    editable: boolean
}

type WindowedContentTileProps = DashboardContentTileProps & { panels: PanelType[] }

// Kept apart from `WindowedContentTile`, so a tile reads the dashboard state only once its card mounts.
function DashboardContentTile({ id, panel, editable }: DashboardContentTileProps): JSX.Element {
    const { panels, disabledReasonFor, onEdit } = useDashboard()
    const actions = useContentTileActions(id, panel)
    const placementActions = useContentTilePlacementActions(id, panel)
    const canSetConfig = !disabledReasonFor('setPanelConfig')
    // `onEdit` changes with every dashboard edit; a stable `setConfig` keeps `PanelView`'s memo, so moving tiles
    // doesn't re-render every panel.
    const onEditRef = useRef(onEdit)
    onEditRef.current = onEdit
    const setConfig = useCallback((config: unknown) => onEditRef.current({ edit: 'setPanelConfig', id, config }), [id])
    return (
        <ContentTile
            panel={panel}
            panels={panels}
            actions={actions}
            placementActions={placementActions}
            editable={editable}
            setConfig={canSetConfig ? setConfig : undefined}
        />
    )
}

/**
 * A content tile whose card mounts only near the scrolled view. The sentinel fills the cell, so the cell is observed
 * whether the card or the placeholder is showing.
 */
function WindowedContentTile({ id, panel, editable, panels }: WindowedContentTileProps): JSX.Element {
    const sentinel = useRef<HTMLSpanElement>(null)
    const mounted = useTileMounted(sentinel)
    return (
        <>
            <span ref={sentinel} aria-hidden className="DashboardTileGrid__sentinel" />
            {mounted ? (
                <DashboardContentTile id={id} panel={panel} editable={editable} />
            ) : (
                <ContentTilePlaceholder panel={panel} definition={findPanel(panels, panel.type)} editable={editable} />
            )}
        </>
    )
}

type TileFrameProps = {
    tile: Tile
    columnPx: number
    editable: boolean
    panels: PanelType[]
    onSectionRows: OnSectionRows
}

/** What a grid cell holds. Memoised on the tile, so a drag in a grid re-renders none of its tiles. */
const TileFrame = memo(function TileFrame({
    tile,
    columnPx,
    editable,
    panels,
    onSectionRows,
}: TileFrameProps): JSX.Element {
    const { id, panel } = tile
    const capturing = useContext(CapturingTileContext) === id
    const content = isSectionPanel(panel) ? (
        <SectionTile
            id={id}
            panel={panel}
            layout={{ columns: tile.place.w, columnPx }}
            editable={editable}
            onSectionRows={onSectionRows}
            renderGrid={renderSectionGrid}
        />
    ) : (
        <WindowedContentTile id={id} panel={panel} editable={editable} panels={panels} />
    )
    return capturing ? <TileMountContext.Provider value={null}>{content}</TileMountContext.Provider> : content
})

function renderSectionGrid(props: SectionGridProps): JSX.Element {
    return <DashboardTileGrid {...props} />
}

export function DashboardTileGrid({
    gridId,
    tiles,
    cols,
    width,
    editable,
    onLiveRows,
}: Omit<SectionGridProps, 'onLiveRows'> & Partial<Pick<SectionGridProps, 'onLiveRows'>>): JSX.Element {
    const { dashboard, onEdit, sizeOf, can, panels } = useDashboard()
    const renderTile = useCallback(
        (tile: Tile, columnPx: number, onSectionRows: OnSectionRows) => (
            <TileFrame
                tile={tile}
                columnPx={columnPx}
                editable={editable}
                panels={panels}
                onSectionRows={onSectionRows}
            />
        ),
        [editable, panels]
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
