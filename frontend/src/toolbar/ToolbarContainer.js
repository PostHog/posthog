import { useActions, useValues } from 'kea'
import { ToolbarContent } from '~/toolbar/ToolbarContent'
import { CloseOutlined } from '@ant-design/icons'
import React from 'react'
import { Elements } from '~/toolbar/elements/Elements'
import { ToolbarButton } from '~/toolbar/button/ToolbarButton'
import { ToolbarDraggable } from '~/toolbar/ToolbarDraggable'
import { dockLogic } from '~/toolbar/dockLogic'
import { elementsLogic } from '~/toolbar/elements/elementsLogic'

export function ToolbarContainer() {
    const { dockStatus, floatStatus, buttonStatus, windowWidth, isAnimating, mode } = useValues(dockLogic)
    const { button } = useActions(dockLogic)
    const { selectedElement } = useValues(elementsLogic)
    const { setSelectedElement } = useActions(elementsLogic)

    const showButton = buttonStatus !== 'disabled'
    const showInvisibleButton = buttonStatus === 'animating' || buttonStatus === 'fading-out'

    const showDock = dockStatus !== 'disabled'
    const showInvisibleDock = dockStatus === 'animating' || dockStatus === 'fading-out'

    const showFloat = floatStatus !== 'disabled'
    const showInvisibleFloat = floatStatus === 'animating' || floatStatus === 'fading-out'

    return (
        <>
            {mode === '' || isAnimating ? null : <Elements />}

            {showButton && windowWidth >= 0 ? (
                <ToolbarDraggable type="button" handle="#button-toolbar">
                    <div id="button-toolbar" className={showInvisibleButton ? 'toolbar-invisible' : ''}>
                        <ToolbarButton />
                    </div>
                </ToolbarDraggable>
            ) : null}

            {showFloat && windowWidth >= 0 ? (
                <ToolbarDraggable type="float" handle=".toolbar-block">
                    <div id="float-toolbar" className={showInvisibleFloat ? 'toolbar-invisible' : ''}>
                        <ToolbarContent type="float" />
                    </div>
                </ToolbarDraggable>
            ) : null}

            {showDock ? (
                <div id="dock-toolbar" className={showInvisibleDock ? 'toolbar-invisible' : ''}>
                    <div
                        className={`toolbar-close-button${dockStatus === 'complete' ? ' visible' : ''}`}
                        onClick={selectedElement ? () => setSelectedElement(null) : button}
                    >
                        <CloseOutlined />
                    </div>
                    <ToolbarContent type="dock" />
                </div>
            ) : null}
        </>
    )
}
