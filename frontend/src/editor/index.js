import '~/editor/styles.scss'

import React, { useRef } from 'react'
import ReactDOM from 'react-dom'
import Simmer from 'simmerjs'
import root from 'react-shadow'
import Draggable from 'react-draggable'
import { getContext, useActions, useValues } from 'kea'
import { Provider } from 'react-redux'
import { Toolbar } from '~/editor/Toolbar'
import { dockLogic } from '~/editor/dockLogic'
import { CloseOutlined } from '@ant-design/icons'
import { initKea } from '~/initKea'
import { useSecondRender } from 'lib/hooks/useSecondRender'

initKea()

window.simmer = new Simmer(window, { depth: 8 })

function Editor({ logic, ...props }) {
    const apiURL = `${props.apiURL}${props.apiURL.endsWith('/') ? '' : '/'}`
    const { dockStatus, floatStatus } = useValues(logic)
    const { dock, float } = useActions(logic)

    const showDocked = dockStatus !== 'disabled'
    const showInvisibleDocked = dockStatus === 'animating' || dockStatus === 'fading-out'

    const showFloating = floatStatus !== 'disabled'
    const showInvisibleFloating = floatStatus === 'animating' || floatStatus === 'fading-out'

    return (
        <>
            {showFloating ? (
                <Draggable handle=".toolbar-block">
                    <div id="floating-toolbar" className={showInvisibleFloating ? 'toolbar-invisible' : ''}>
                        <button onClick={dock}>Dock</button>
                        <Toolbar {...props} type="floating" apiURL={apiURL} />
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
                    <Toolbar {...props} type="docked" apiURL={apiURL} />
                </div>
            ) : null}
        </>
    )
}

function App(props) {
    const shadowRef = useRef(null)
    const logic = dockLogic({ shadowRef })

    // this runs after the shadow root has been added to the dom
    const didRender = useSecondRender(() => {
        function addElement(element) {
            const { shadowRoot } = shadowRef.current || window.document.getElementById('__POSTHOG_TOOLBAR__')
            shadowRoot.getElementById('posthog-toolbar-styles').appendChild(element)
        }

        if (window.__PHGTLB_STYLES__) {
            window.__PHGTLB_STYLES__.forEach(element => addElement(element))
        }
        window.__PHGTLB_ADD_STYLES__ = element => addElement(element)
    })

    return (
        <>
            <root.div id="__POSTHOG_TOOLBAR__" ref={shadowRef}>
                <div id="posthog-toolbar-styles" />
                {didRender ? <Editor {...props} logic={logic} shadowRef={shadowRef} /> : null}
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
                jsURL={editorParams.jsURL || editorParams.apiURL}
                apiURL={editorParams.apiURL}
                temporaryToken={editorParams.temporaryToken}
                actionId={editorParams.actionId}
                startMinimized={editorParams.minimized}
            />
        </Provider>,
        container
    )
}
