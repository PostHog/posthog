import React from 'react'
import ReactDOM from 'react-dom'
import Simmer from 'simmerjs'
import root from 'react-shadow'
import Draggable from 'react-draggable'
import { getContext, useActions, useValues } from 'kea'
import { Provider } from 'react-redux'
import { styles } from '~/editor/styles'
import { Toolbar } from '~/editor/Toolbar'
import { dockLogic } from '~/editor/dockLogic'
import { Button } from 'antd'

window.simmer = new Simmer(window, { depth: 8 })

function App(props) {
    const apiURL = `${props.apiURL}${props.apiURL.endsWith('/') ? '' : '/'}`
    const logic = dockLogic({ mode: 'float' })
    const { dockStatus, floatStatus } = useValues(logic)
    const { dock, float } = useActions(logic)

    const showToolbar = dockStatus !== 'disabled'
    const showInvisibleToolbar = dockStatus === 'animating' || dockStatus === 'fading-out'

    const showDraggable = floatStatus !== 'disabled'
    const showInvisibleDraggable = floatStatus === 'animating' || floatStatus === 'fading-out'

    return (
        <>
            <root.div>
                <link href={`${apiURL}static/editor.css`} rel="stylesheet" crossOrigin="anonymous" />
                <style>{styles}</style>

                {showDraggable ? (
                    <Draggable handle=".drag-bar">
                        <div className={`box${showInvisibleDraggable ? ' toolbar-invisible' : ''}`}>
                            <button style={{ float: 'right' }} onClick={dock}>
                                Dock
                            </button>
                            <Toolbar {...props} apiURL={apiURL} />
                        </div>
                    </Draggable>
                ) : null}

                {showToolbar ? (
                    <div id="toolbar" className={`${showInvisibleToolbar ? 'toolbar-invisible' : ''}`}>
                        <Button type="link" onClick={float}>
                            {'<< Float'}
                        </Button>
                        <Toolbar {...props} apiURL={apiURL} />
                    </div>
                ) : null}
            </root.div>
        </>
    )
}

window.ph_load_editor = function(editorParams) {
    let container = document.createElement('div')
    document.body.appendChild(container)

    ReactDOM.render(
        <Provider store={getContext().store}>
            <App
                apiURL={editorParams.apiURL}
                temporaryToken={editorParams.temporaryToken}
                actionId={editorParams.actionId}
                startMinimized={editorParams.minimized}
            />
        </Provider>,
        container
    )
}
