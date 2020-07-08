import React from 'react'
import { Fade } from 'lib/components/Fade/Fade'
import Draggable from 'react-draggable'

export function ButtonWindow({ name, visible, position, savePosition, close, label, icon, children }) {
    return (
        <Fade visible={visible}>
            <Draggable
                handle=".toolbar-info-window-title"
                position={position}
                onDrag={(e, { x, y }) => savePosition(x, y)}
                onStop={(e, { x, y }) => savePosition(x, y)}
            >
                <div className={`toolbar-info-windows ${name}-button-window`}>
                    <div className="toolbar-info-window-title">
                        {icon}
                        <span className="window-label">{label}</span>
                        <span className="close-button" onClick={close}>
                            X
                        </span>
                    </div>
                    {children}
                </div>
            </Draggable>
        </Fade>
    )
}
