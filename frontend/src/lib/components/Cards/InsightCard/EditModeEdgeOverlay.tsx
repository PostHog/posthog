import React from 'react'

interface EditModeEdgeOverlayProps {
    onEnterEditMode: () => void
}

const edgeOverlayBaseStyle: React.CSSProperties = {
    position: 'absolute',
    zIndex: 5,
    padding: 0,
    margin: 0,
    border: 'none',
    background: 'none',
}

export const EditModeEdgeOverlay: React.FC<EditModeEdgeOverlayProps> = ({ onEnterEditMode }) => {
    const handlePress = (event: React.MouseEvent<HTMLDivElement>): void => {
        // Treat any press (click or drag attempt) as intent to edit
        event.preventDefault()
        event.stopPropagation()
        onEnterEditMode()
    }

    const edges: { style: React.CSSProperties; cursor: React.CSSProperties['cursor'] }[] = [
        // top – vertical resize cursor
        { style: { left: 0, right: 0, top: -6, height: 12 }, cursor: 'ns-resize' },
        // bottom – vertical resize cursor
        { style: { left: 0, right: 0, bottom: -6, height: 12 }, cursor: 'ns-resize' },
        // left – horizontal resize cursor
        { style: { top: 0, bottom: 0, left: -6, width: 12 }, cursor: 'ew-resize' },
        // right – horizontal resize cursor
        { style: { top: 0, bottom: 0, right: -6, width: 12 }, cursor: 'ew-resize' },
    ]

    return (
        <>
            {edges.map(({ style, cursor }, index) => (
                <div
                    key={index}
                    onMouseDown={handlePress}
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
