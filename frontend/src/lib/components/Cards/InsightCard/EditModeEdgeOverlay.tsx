import React from 'react'

export type EditModeEdge = 'n' | 's' | 'w' | 'e'

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

const edges: { edge: EditModeEdge; style: React.CSSProperties; cursor: React.CSSProperties['cursor'] }[] = [
    // top – vertical resize cursor
    { edge: 'n', style: { left: 0, right: 0, top: -6, height: 12 }, cursor: 'ns-resize' },
    // bottom – vertical resize cursor
    { edge: 's', style: { left: 0, right: 0, bottom: -6, height: 12 }, cursor: 'ns-resize' },
    // left – horizontal resize cursor
    { edge: 'w', style: { top: 0, bottom: 0, left: -6, width: 12 }, cursor: 'ew-resize' },
    // right – horizontal resize cursor
    { edge: 'e', style: { top: 0, bottom: 0, right: -6, width: 12 }, cursor: 'ew-resize' },
]

export const EditModeEdgeOverlay: React.FC<EditModeEdgeOverlayProps> = ({ onEnterEditMode }) => {
    const handlePress = (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge): void => {
        // Treat any press (click or drag attempt) as intent to edit
        event.preventDefault()
        event.stopPropagation()
        onEnterEditMode(event, edge)
    }

    return (
        <>
            {edges.map(({ edge, style, cursor }) => (
                <div
                    key={edge}
                    onMouseDown={(event) => handlePress(event, edge)}
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
