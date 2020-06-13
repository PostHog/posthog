import { useActions, useValues } from 'kea'
import { ToolbarContent } from '~/toolbar/ToolbarContent'
import { CloseOutlined } from '@ant-design/icons'
import React from 'react'
import { Heatmap } from '~/toolbar/shared/Heatmap'
import { ToolbarButton } from '~/toolbar/button/ToolbarButton'
import { ToolbarDraggable } from '~/toolbar/ToolbarDraggable'
import { dockLogic } from '~/toolbar/dockLogic'

export function ToolbarContainer({ ...props }) {
    const apiURL = `${props.apiURL}${props.apiURL.endsWith('/') ? '' : '/'}`
    const { dockStatus, floatStatus, buttonStatus, windowWidth } = useValues(dockLogic)
    const { button } = useActions(dockLogic)

    const showButton = buttonStatus !== 'disabled'
    const showInvisibleButton = buttonStatus === 'animating' || buttonStatus === 'fading-out'

    const showDock = dockStatus !== 'disabled'
    const showInvisibleDock = dockStatus === 'animating' || dockStatus === 'fading-out'

    const showFloat = floatStatus !== 'disabled'
    const showInvisibleFloat = floatStatus === 'animating' || floatStatus === 'fading-out'

    return (
        <>
            <Heatmap {...props} dockLogic={dockLogic} />

            {showButton && windowWidth >= 0 ? (
                <ToolbarDraggable type="button" handle="#button-toolbar">
                    <div id="button-toolbar" className={showInvisibleButton ? 'toolbar-invisible' : ''}>
                        <ToolbarButton {...props} type="button" apiURL={apiURL} />
                    </div>
                </ToolbarDraggable>
            ) : null}

            {showFloat && windowWidth >= 0 ? (
                <ToolbarDraggable type="float" handle=".toolbar-block">
                    <div id="float-toolbar" className={showInvisibleFloat ? 'toolbar-invisible' : ''}>
                        <ToolbarContent {...props} type="float" apiURL={apiURL} />
                    </div>
                </ToolbarDraggable>
            ) : null}

            {showDock ? (
                <div id="dock-toolbar" className={showInvisibleDock ? 'toolbar-invisible' : ''}>
                    <div
                        className={`toolbar-close-button${dockStatus === 'complete' ? ' visible' : ''}`}
                        onClick={button}
                    >
                        <CloseOutlined />
                    </div>
                    <ToolbarContent {...props} type="dock" apiURL={apiURL} />
                </div>
            ) : null}
        </>
    )
}
