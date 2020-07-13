import React from 'react'
import { Fade } from 'lib/components/Fade/Fade'
import Draggable from 'react-draggable'

export function ButtonWindow({ name, visible, position, savePosition, close, label, icon, children }) {
    return (
        <Fade visible={visible}>
            <Draggable
                handle=".toolbar-info-window-draggable"
                position={position}
                onDrag={(e, { x, y }) => savePosition(x, y)}
                onStop={(e, { x, y }) => savePosition(x, y)}
            >
                <div className={`toolbar-info-windows ${name}-button-window`}>
                    <div className="toolbar-info-window-title">
                        <div className="toolbar-info-window-draggable">
                            {icon}
                            <div className="window-label">{label}</div>
                        </div>
                        <div className="close-button" onClick={close}>
                            X
                        </div>
                    </div>
                    {children}
                </div>
            </Draggable>
        </Fade>
    )
}
