import React from 'react'
import { useActions, useValues } from 'kea'
import { DockedToolbar } from '~/toolbar/DockedToolbar'
import { CloseOutlined } from '@ant-design/icons'
import { Elements } from '~/toolbar/elements/Elements'
import { dockLogic } from '~/toolbar/dockLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'
import { DraggableButton } from '~/toolbar/button/DraggableButton'
import { hot } from 'react-hot-loader/root'

export const ToolbarContainer = hot(_ToolbarContainer)
function _ToolbarContainer() {
    const { dockStatus, buttonStatus, windowWidth, isAnimating, mode } = useValues(dockLogic)
    const { button } = useActions(dockLogic)
    const { selectedElement } = useValues(elementsLogic)
    const { setSelectedElement } = useActions(elementsLogic)

    const showButton = buttonStatus !== 'disabled'
    const showInvisibleButton = buttonStatus === 'animating' || buttonStatus === 'fading-out'

    const showDock = dockStatus !== 'disabled'
    const showInvisibleDock = dockStatus === 'animating' || dockStatus === 'fading-out'

    return (
        <>
            {mode === '' || isAnimating ? null : <Elements />}

            {showButton && windowWidth >= 0 ? <DraggableButton showInvisibleButton={showInvisibleButton} /> : null}

            {showDock ? (
                <div id="dock-toolbar" className={showInvisibleDock ? 'toolbar-invisible' : ''}>
                    <div
                        className={`toolbar-close-button${dockStatus === 'complete' ? ' visible' : ''}`}
                        onClick={selectedElement ? () => setSelectedElement(null) : button}
                    >
                        <CloseOutlined />
                    </div>
                    <DockedToolbar type="dock" />
                </div>
            ) : null}
        </>
    )
}
