import { useActions, useValues } from 'kea'
import Draggable from 'react-draggable'
import { ToolbarContent } from '~/toolbar/ToolbarContent'
import { CloseOutlined } from '@ant-design/icons'
import React from 'react'
import { ToolbarButton } from '~/toolbar/ToolbarButton'

export function ToolbarContainer({ dockLogic, ...props }) {
    const apiURL = `${props.apiURL}${props.apiURL.endsWith('/') ? '' : '/'}`
    const { dockStatus, floatStatus, buttonStatus } = useValues(dockLogic)
    const { button } = useActions(dockLogic)

    const showButton = buttonStatus !== 'disabled'
    const showInvisibleButton = buttonStatus === 'animating' || buttonStatus === 'fading-out'

    const showDock = dockStatus !== 'disabled'
    const showInvisibleDock = dockStatus === 'animating' || dockStatus === 'fading-out'

    const showFloat = floatStatus !== 'disabled'
    const showInvisibleFloat = floatStatus === 'animating' || floatStatus === 'fading-out'

    return (
        <>
            {showButton ? (
                <Draggable handle="#button-toolbar">
                    <div id="button-toolbar" className={showInvisibleButton ? 'toolbar-invisible' : ''}>
                        <ToolbarButton {...props} dockLogic={dockLogic} type="button" apiURL={apiURL} />
                    </div>
                </Draggable>
            ) : null}

            {showFloat ? (
                <Draggable handle=".toolbar-block">
                    <div id="float-toolbar" className={showInvisibleFloat ? 'toolbar-invisible' : ''}>
                        <ToolbarContent {...props} dockLogic={dockLogic} type="float" apiURL={apiURL} />
                    </div>
                </Draggable>
            ) : null}

            {showDock ? (
                <div id="dock-toolbar" className={showInvisibleDock ? 'toolbar-invisible' : ''}>
                    <div
                        className={`toolbar-close-button${dockStatus === 'complete' ? ' visible' : ''}`}
                        onClick={button}
                    >
                        <CloseOutlined />
                    </div>
                    <ToolbarContent {...props} dockLogic={dockLogic} type="dock" apiURL={apiURL} />
                </div>
            ) : null}
        </>
    )
}
