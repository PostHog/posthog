import { useActions, useValues } from 'kea'
import Draggable from 'react-draggable'
import { ToolbarContent } from '~/toolbar/ToolbarContent'
import { CloseOutlined } from '@ant-design/icons'
import React from 'react'

export function ToolbarContainer({ dockLogic, ...props }) {
    const apiURL = `${props.apiURL}${props.apiURL.endsWith('/') ? '' : '/'}`
    const { dockStatus, floatStatus } = useValues(dockLogic)
    const { float } = useActions(dockLogic)

    const showDocked = dockStatus !== 'disabled'
    const showInvisibleDocked = dockStatus === 'animating' || dockStatus === 'fading-out'

    const showFloating = floatStatus !== 'disabled'
    const showInvisibleFloating = floatStatus === 'animating' || floatStatus === 'fading-out'

    return (
        <>
            {showFloating ? (
                <Draggable handle=".toolbar-block">
                    <div id="floating-toolbar" className={showInvisibleFloating ? 'toolbar-invisible' : ''}>
                        <ToolbarContent {...props} dockLogic={dockLogic} type="floating" apiURL={apiURL} />
                    </div>
                </Draggable>
            ) : null}

            {showDocked ? (
                <div id="docked-toolbar" className={showInvisibleDocked ? 'toolbar-invisible' : ''}>
                    <div
                        className={`toolbar-close-button${dockStatus === 'complete' ? ' visible' : ''}`}
                        onClick={float}
                    >
                        <CloseOutlined />
                    </div>
                    <ToolbarContent {...props} dockLogic={dockLogic} type="docked" apiURL={apiURL} />
                </div>
            ) : null}
        </>
    )
}
