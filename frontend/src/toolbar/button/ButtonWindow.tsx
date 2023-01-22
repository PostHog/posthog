import { Fade } from 'lib/components/Fade/Fade'
import Draggable from 'react-draggable'
import { CloseOutlined } from '@ant-design/icons'
import { useEffect, useRef } from 'react'
import { useActions } from 'kea'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
interface ButtonWindowProps {
    name: string
    visible: boolean
    position: { x: number; y: number }
    savePosition: (x: number, y: number) => void
    close: () => void
    label: string | JSX.Element
    tagComponent?: null | JSX.Element
    children?: JSX.Element
}

export function ButtonWindow({
    name,
    visible,
    position,
    savePosition,
    close,
    label,
    tagComponent,
    children,
}: ButtonWindowProps): JSX.Element {
    const windowRef = useRef<HTMLDivElement | null>(null)
    const { storeButtonWindowRef } = useActions(toolbarButtonLogic)
    useEffect(() => {
        // store a ref to the window here
        // it can be used in children to for e.g. ensure tooltips are visible
        storeButtonWindowRef(windowRef)
    }, [storeButtonWindowRef, windowRef.current, visible])

    return (
        <Fade visible={visible}>
            <Draggable
                handle=".toolbar-info-window-draggable"
                position={position}
                onDrag={(_, { x, y }) => savePosition(x, y)}
                onStop={(_, { x, y }) => savePosition(x, y)}
            >
                <div className={`toolbar-info-windows ${name}-button-window`} ref={windowRef}>
                    <div className="toolbar-info-window-title">
                        <div className="toolbar-info-window-draggable">
                            <div className="window-label">{label}</div>
                            {tagComponent}
                        </div>
                        <CloseOutlined className="close-button" onClick={close} />
                    </div>
                    {children}
                </div>
            </Draggable>
        </Fade>
    )
}
