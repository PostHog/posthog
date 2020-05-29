import React from 'react'
import ReactDOM from 'react-dom'
import Simmer from 'simmerjs'
import root from 'react-shadow'
import Draggable from 'react-draggable'
import { getContext, kea, useActions, useValues } from 'kea'
import { Provider } from 'react-redux'
import { styles } from '~/editor/styles'
import { ToolBar } from '~/editor/Toolbar'

window.simmer = new Simmer(window, { depth: 8 })

// props:
// - mode: 'dock' | 'zoom'
const editorLogic = kea({
    // transition steps:
    // - dock: disabled, animating, fading, complete
    // - float: disabled, animating, fading, complete
    // call dock/float and it will
    actions: () => ({
        dock: () => ({ mode: 'dock' }),
        dockAnimated: () => ({ mode: 'dock' }),
        dockFaded: () => ({ mode: 'dock' }),
        float: () => ({ mode: 'float' }),
        floatAnimated: () => ({ mode: 'float' }),
        floatFaded: () => ({ mode: 'float' }),
    }),

    reducers: ({ props }) => ({
        docked: [
            props.mode === 'dock',
            {
                dock: () => true,
                float: () => false,
            },
        ],
        dockStatus: [
            props.mode === 'dock' ? 'complete' : 'disabled',
            {
                dock: () => 'animating',
                dockAnimated: () => 'fading-in',
                dockFaded: () => 'complete',
                float: () => 'fading-out',
                floatAnimated: () => 'disabled',
                floatFaded: () => 'disabled',
            },
        ],
        floatStatus: [
            props.mode === 'float' ? 'complete' : 'disabled',
            {
                float: () => 'animating',
                floatAnimated: () => 'fading-in',
                floatFaded: () => 'complete',
                dock: () => 'fading-out',
                dockAnimated: () => 'disabled',
                dockFaded: () => 'disabled',
            },
        ],
    }),

    listeners: ({ sharedListeners }) => ({
        dock: sharedListeners.zoom,
        float: sharedListeners.zoom,
    }),

    sharedListeners: ({ actions }) => ({
        zoom: async ({ mode }, breakpoint) => {
            window.requestAnimationFrame(() => {
                window.document.body.style.overflow = 'hidden'
                if (mode === 'dock') {
                    initZoomOut()
                } else {
                    resetZoomOut()
                }
            })

            await breakpoint(500)
            window.requestAnimationFrame(() => {
                window.document.body.style.overflow = 'auto'
                mode === 'dock' ? actions.dockAnimated() : actions.floatAnimated()
            })

            await breakpoint(500)
            window.requestAnimationFrame(() => {
                mode === 'dock' ? actions.dockFaded() : actions.floatFaded()
            })
        },
    }),
})

function App(props) {
    const logic = editorLogic({ mode: 'float' })
    const { dockStatus, floatStatus } = useValues(logic)
    const { dock, float } = useActions(logic)

    const showToolbar = dockStatus !== 'disabled'
    const showInvisibleToolbar = dockStatus === 'animating' || dockStatus === 'fading-out'

    const showDraggable = floatStatus !== 'disabled'
    const showInvisibleDraggable = floatStatus === 'animating' || floatStatus === 'fading-out'

    return (
        <>
            <root.div>
                <link href={props.apiURL + 'static/main.css'} rel="stylesheet" crossOrigin="anonymous" />
                <style>{styles}</style>

                {showDraggable ? (
                    <Draggable handle=".drag-bar">
                        <div className={`box${showInvisibleDraggable ? ' toolbar-invisible' : ''}`}>
                            <button style={{ float: 'right' }} onClick={dock}>
                                Dock
                            </button>
                            <ToolBar {...props} />
                        </div>
                    </Draggable>
                ) : null}

                {showToolbar ? (
                    <div id="toolbar" className={`${showInvisibleToolbar ? 'toolbar-invisible' : ''}`}>
                        <button style={{ float: 'right' }} onClick={float}>
                            Float
                        </button>
                        <ToolBar {...props} />
                    </div>
                ) : null}
            </root.div>
        </>
    )
}

let listener

function resetZoomOut() {
    window.document.querySelector('html').style.background = 'auto'
    window.document.body.style.transform = 'none'
    window.document.body.style.width = `auto`
    window.document.body.style.minHeight = `auto`
    window.document.body.style.minHeight = `auto`

    window.removeEventListener('scroll', listener)
}

function initZoomOut(zoom = 0.7) {
    window.document.querySelector('html').style.background = '#a1a3ae'
    window.document.body.style.transform = `scale(1) translate(0px 0px)`
    window.document.body.style.willChange = 'transform'
    window.document.body.style.transition = 'transform ease 0.5s'
    window.document.body.style.transformOrigin = `top left`
    window.document.body.style.width = `100vw`
    window.document.body.style.minHeight = `100%`
    if (!window.document.body.style.backgroundColor) {
        window.document.body.style.backgroundColor = 'white'
    }

    window.requestAnimationFrame(() => {
        window.document.body.style.transform = `scale(${zoom}) translate(${20 / zoom}px, ${20 / zoom}px)`
    })

    listener = function() {
        const bodyElements = [...document.body.getElementsByTagName('*')]
        bodyElements
            .filter(x => getComputedStyle(x, null).getPropertyValue('position') === 'fixed')
            .forEach(e => {
                const h = (window.pageYOffset + (window.pageYOffset > 20 ? -20 : 0)) / zoom
                e.style.marginTop = `${h}px`
                e.setAttribute('data-posthog-fix-fixed', 'yes')
            })

        const tweakedElements = [...document.querySelectorAll('[data-posthog-fix-fixed=yes]')]
        tweakedElements
            .filter(x => getComputedStyle(x, null).getPropertyValue('position') !== 'fixed')
            .forEach(e => {
                e.style.marginTop = 0
            })
    }
    window.addEventListener('scroll', listener)

    // toolbar = document.createElement('posthog-toolbar');
    // document.body.appendChild(toolbar);
    // window.addEventListener('scroll', function(e) {
    //   toolbar.shadowRoot.getElementById('toolbar').style.marginTop = `${window.pageYOffset / zoom}px`;
    // })
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
            />
        </Provider>,
        container
    )
}
