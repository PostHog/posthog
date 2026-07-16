import React, { useRef, useState } from 'react'

import { DashboardResizeHandles } from 'lib/components/Cards/handles'

export type EditModeEdge = 'n' | 's' | 'w' | 'e' | 'nw' | 'ne' | 'sw' | 'se'

interface EditModeEdgeOverlayProps {
    onEnterEditMode: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
}

const edgeOverlayBaseStyle: React.CSSProperties = {
    position: 'absolute',
    zIndex: 5,
    padding: 0,
    margin: 0,
    border: 'none',
    background: 'none',
}

// Top/bottom zones hug the border and reach mostly *into* the tile: the inline "insert tile" overlay owns the
// row gap between tiles (see InsertTileOverlay), so keeping these off the gap avoids fighting it for the same
// pixels. They still win the shared border pixel via a higher z-index. Left/right never touch the insert line.
const TOP_BOTTOM_Z = 7
// Corners sit above edges so a press in the corner resolves to the diagonal handle.
const cornerZoneStyle: React.CSSProperties = { zIndex: TOP_BOTTOM_Z, width: 18, height: 18 }

const zones: { edge: EditModeEdge; style: React.CSSProperties; cursor: React.CSSProperties['cursor'] }[] = [
    // Shallow on top (the card header/menu lives just below) and deeper on the bottom for a comfortable target.
    { edge: 'n', style: { left: 0, right: 0, top: -2, height: 10, zIndex: TOP_BOTTOM_Z }, cursor: 'ns-resize' },
    { edge: 's', style: { left: 0, right: 0, bottom: -2, height: 14, zIndex: TOP_BOTTOM_Z }, cursor: 'ns-resize' },
    { edge: 'w', style: { top: 0, bottom: 0, left: -6, width: 12 }, cursor: 'ew-resize' },
    { edge: 'e', style: { top: 0, bottom: 0, right: -6, width: 12 }, cursor: 'ew-resize' },
    { edge: 'nw', style: { ...cornerZoneStyle, top: -2, left: -2 }, cursor: 'nw-resize' },
    { edge: 'ne', style: { ...cornerZoneStyle, top: -2, right: -2 }, cursor: 'ne-resize' },
    { edge: 'sw', style: { ...cornerZoneStyle, bottom: -2, left: -2 }, cursor: 'sw-resize' },
    { edge: 'se', style: { ...cornerZoneStyle, bottom: -2, right: -2 }, cursor: 'se-resize' },
]

export const EditModeEdgeOverlay: React.FC<EditModeEdgeOverlayProps> = ({ onEnterEditMode }) => {
    const [hovering, setHovering] = useState(false)
    // Count entered zones rather than toggling a boolean, so following the border across overlapping
    // edge/corner zones never dips to "not hovering" for a frame and flickers the handles.
    const hoverCount = useRef(0)

    const handlePress = (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge): void => {
        // Treat any press (click or drag attempt) as intent to edit
        event.preventDefault()
        event.stopPropagation()
        onEnterEditMode(event, edge)
    }

    return (
        <>
            {hovering && <DashboardResizeHandles />}
            {zones.map(({ edge, style, cursor }) => (
                <div
                    key={edge}
                    onMouseDown={(event) => handlePress(event, edge)}
                    onMouseEnter={() => {
                        hoverCount.current += 1
                        setHovering(true)
                    }}
                    onMouseLeave={() => {
                        hoverCount.current = Math.max(0, hoverCount.current - 1)
                        if (hoverCount.current === 0) {
                            setHovering(false)
                        }
                    }}
                    aria-hidden="true"
                    title="Click to edit layout"
                    data-attr="dashboard-edit-mode-from-card-edge"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ ...edgeOverlayBaseStyle, ...style, cursor }}
                />
            ))}
        </>
    )
}
