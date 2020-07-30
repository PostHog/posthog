import React from 'react'
import { Fade } from 'lib/components/Fade/Fade'
import Draggable from 'react-draggable'

interface ButtonWindowProps {
    name: string
    visible: boolean
    position: { x: number; y: number }
    savePosition: (x: number, y: number) => void
    close: () => void
    label: string | JSX.Element
    icon: string | JSX.Element
    children?: JSX.Element
}

export function ButtonWindow({
    name,
    visible,
    position,
    savePosition,
    close,
    label,
    icon,
    children,
}: ButtonWindowProps): JSX.Element {
    return (
        <Fade visible={visible}>
            <Draggable
                handle=".toolbar-info-window-draggable"
                position={position}
                onDrag={(_, { x, y }) => savePosition(x, y)}
                onStop={(_, { x, y }) => savePosition(x, y)}
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
