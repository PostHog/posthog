import './DashboardTileMovementPreview.scss'

import { DashboardGridCompaction } from '../../dashboardCustomization'

const GRID_STROKE = 'var(--color-border-primary)'
const EXISTING_TILE = 'var(--data-color-3)'
const MOVED_TILE = 'var(--data-color-1)'
const DISPLACED_TILE = 'var(--data-color-5)'

interface DashboardTileMovementPreviewProps {
    mode: DashboardGridCompaction
}

function Tile({ x, y, fill, className }: { x: number; y: number; fill: string; className?: string }): JSX.Element {
    return <rect className={className} x={x * 15.5 + 3} y={y * 16 + 11} width="12.5" height="13" rx="2" fill={fill} />
}

function MovementTiles({ mode }: DashboardTileMovementPreviewProps): JSX.Element {
    if (mode === DashboardGridCompaction.Vertical) {
        return (
            <>
                <Tile x={0} y={0} fill={EXISTING_TILE} />
                <Tile x={0} y={1} fill={EXISTING_TILE} />
                <Tile x={0} y={2} fill={EXISTING_TILE} />
                <Tile x={1} y={2} fill={MOVED_TILE} className="dashboard-tile-movement-preview__move-up-double" />
                <Tile x={2} y={1} fill={DISPLACED_TILE} className="dashboard-tile-movement-preview__move-up" />
            </>
        )
    }

    if (mode === DashboardGridCompaction.Horizontal) {
        return (
            <>
                <Tile x={0} y={0} fill={EXISTING_TILE} />
                <Tile x={1} y={0} fill={DISPLACED_TILE} className="dashboard-tile-movement-preview__move-right" />
                <Tile x={1} y={1} fill={MOVED_TILE} className="dashboard-tile-movement-preview__move-into-row" />
            </>
        )
    }

    return (
        <>
            <Tile x={0} y={0} fill={MOVED_TILE} className="dashboard-tile-movement-preview__resize-right" />
            <Tile x={1} y={0} fill={DISPLACED_TILE} className="dashboard-tile-movement-preview__move-down" />
            <Tile x={2} y={1} fill={EXISTING_TILE} />
        </>
    )
}

export function DashboardTileMovementPreview({ mode }: DashboardTileMovementPreviewProps): JSX.Element {
    return (
        <svg
            viewBox="0 0 48 58"
            className="dashboard-tile-movement-preview mt-0.5 h-12 w-10 shrink-0"
            fill="none"
            aria-hidden="true"
        >
            <rect x="1" y="9" width="46" height="46" rx="4" fill="var(--color-bg-light)" stroke={GRID_STROKE} />
            <path d="M16.5 9V55M32 9V55M1 25H47M1 41H47" stroke={GRID_STROKE} strokeWidth="0.75" opacity="0.7" />
            <MovementTiles mode={mode} />
        </svg>
    )
}
