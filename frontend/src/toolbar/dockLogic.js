import { kea } from 'kea'
import {
    attachDockScrollListener,
    removeDockScrollListener,
    applyDockBodyStyles,
    updateDockToolbarVariables,
    keepInBounds,
} from '~/toolbar/dockUtils'

// props:
// - shadowRef: shadowRoot ref
export const dockLogic = kea({
    props: {
        shadowRef: 'required',
        padding: 'optional',
    },

    // transition steps:
    // - dock: disabled, animating, fading, complete
    // - float: disabled, animating, fading, complete
    // call dock/float and it will start
    actions: () => ({
        // public
        button: true,
        dock: true,
        float: true,
        hideButton: true,
        update: true,

        // private
        buttonAnimated: true,
        buttonFaded: true,
        dockAnimated: true,
        dockFaded: true,
        floatAnimated: true,
        floatFaded: true,
        hideButtonAnimated: true,
        setMode: (mode, update = false) => ({
            mode,
            update,
            windowWidth: window.innerWidth,
            windowHeight: window.innerHeight,
        }),

        saveDragPosition: (mode, x, y) => ({ mode, x, y }),
    }),

    reducers: () => ({
        mode: [
            '',
            {
                button: () => 'button',
                dock: () => 'dock',
                float: () => 'float',
                hide: () => '',
            },
        ],
        lastMode: [
            '',
            { persist: true },
            {
                button: () => 'button',
                dock: () => 'dock',
                float: () => 'float',
            },
        ],
        windowWidth: [
            -1,
            {
                setMode: (_, { windowWidth }) => windowWidth,
            },
        ],
        windowHeight: [
            -1,
            {
                setMode: (_, { windowHeight }) => windowHeight,
            },
        ],
        dockStatus: [
            'disabled',
            {
                dock: () => 'animating',
                dockAnimated: () => 'fading-in',
                dockFaded: () => 'complete',

                float: state => (state === 'disabled' ? 'disabled' : 'fading-out'),
                floatAnimated: () => 'disabled',
                floatFaded: () => 'disabled',
                button: state => (state === 'disabled' ? 'disabled' : 'fading-out'),
                buttonAnimated: () => 'disabled',
                buttonFaded: () => 'disabled',
            },
        ],
        floatStatus: [
            'disabled',
            {
                float: () => 'animating',
                floatAnimated: () => 'fading-in',
                floatFaded: () => 'complete',

                button: state => (state === 'disabled' ? 'disabled' : 'fading-out'),
                buttonAnimated: () => 'disabled',
                buttonFaded: () => 'disabled',
                dock: state => (state === 'disabled' ? 'disabled' : 'fading-out'),
                dockAnimated: () => 'disabled',
                dockFaded: () => 'disabled',
            },
        ],
        buttonStatus: [
            'disabled',
            {
                button: () => 'animating',
                buttonAnimated: () => 'fading-in',
                buttonFaded: () => 'complete',

                dock: state => (state === 'disabled' ? 'disabled' : 'fading-out'),
                dockAnimated: () => 'disabled',
                dockFaded: () => 'disabled',
                float: state => (state === 'disabled' ? 'disabled' : 'fading-out'),
                floatAnimated: () => 'disabled',
                floatFaded: () => 'disabled',

                hideButton: state => (state === 'disabled' ? 'disabled' : 'fading-out'),
                hideButtonAnimated: () => 'disabled',
            },
        ],
        lastDragPosition: [
            {},
            { persist: true },
            {
                saveDragPosition: (state, { mode, x, y }) => ({ ...state, [mode]: { x, y } }),
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        sidebarWidth: [() => [], () => 300],
        padding: [
            () => [selectors.windowWidth],
            windowWidth => (windowWidth > 1200 ? Math.min(30 + (windowWidth - 1200) * 0.3, 60) : 30),
        ],
        bodyWidth: [
            () => [selectors.windowWidth, selectors.sidebarWidth, selectors.padding],
            (windowWidth, sidebarWidth, padding) => windowWidth - sidebarWidth - 3 * padding,
        ],
        zoom: [() => [selectors.bodyWidth, selectors.windowWidth], (bodyWidth, windowWidth) => bodyWidth / windowWidth],
        defaultPositions: [
            () => [selectors.windowWidth, selectors.windowHeight, selectors.lastDragPosition],
            (windowWidth, windowHeight, lastDragPositions) => {
                if (windowWidth < 0 || windowHeight < 0) {
                    return lastDragPositions
                }
                const positions = {}
                ;['button', 'float'].forEach(mode => {
                    const width = mode === 'button' ? 0 : 300
                    const widthPadding = mode === 'button' ? 60 : 20

                    const height = mode === 'button' ? 0 : 300
                    const heightPadding = mode === 'button' ? 80 : 20

                    positions[mode] = lastDragPositions[mode]
                        ? {
                              x: keepInBounds(
                                  lastDragPositions[mode].x,
                                  widthPadding,
                                  windowWidth - width - widthPadding
                              ),
                              y: keepInBounds(
                                  lastDragPositions[mode].y,
                                  heightPadding,
                                  windowHeight - height - heightPadding
                              ),
                          }
                        : {
                              x: windowWidth - width - widthPadding,
                              y: heightPadding,
                          }
                })
                return positions
            },
        ],
    }),

    events: ({ cache, actions, values }) => ({
        afterMount: () => {
            window.__POSTHOG_SET_MODE__ = actions.setMode // export this for debugging in case it goes wrong client side
            cache.listener = () => actions.update()
            window.addEventListener('scroll', cache.listener)
            window.addEventListener('resize', cache.listener)
            window.requestAnimationFrame(() => {
                if (values.lastMode === 'dock') {
                    actions.dock()
                } else if (values.lastMode === 'float') {
                    actions.float()
                } else {
                    actions.button()
                }
            })
        },
        beforeUnmount: () => {
            window.removeEventListener('scroll', cache.listener)
            window.removeEventListener('resize', cache.listener)
        },
    }),

    listeners: ({ actions, values, props }) => ({
        button: () => actions.setMode('button', false),
        dock: () => actions.setMode('dock', false),
        float: () => actions.setMode('float', false),
        hideButton: () => actions.setMode('', false),
        update: () => actions.setMode(values.mode, true),
        setMode: async ({ mode, update }, breakpoint) => {
            const { padding, sidebarWidth, zoom } = values
            const bodyStyle = window.document.body.style
            const htmlStyle = window.document.querySelector('html').style
            const shadowRef = props.shadowRef

            // Update CSS variables (--zoom, etc) in #dock-toolbar inside the shadow root
            shadowRef?.current
                ? updateDockToolbarVariables(shadowRef, zoom, padding, sidebarWidth)
                : window.requestAnimationFrame(() => updateDockToolbarVariables(shadowRef, zoom, padding, sidebarWidth))

            // if update (scroll, resize) vs toggle between float<->dock
            if (update) {
                if (mode === 'dock') {
                    window.requestAnimationFrame(() => {
                        // Set transform and other style attributes on <body> and <html>
                        applyDockBodyStyles(htmlStyle, bodyStyle, zoom, padding, false)
                    })
                }
            } else {
                // Must change state
                // First tick.
                window.requestAnimationFrame(() => {
                    bodyStyle.overflow = 'hidden'
                    if (mode === 'dock') {
                        applyDockBodyStyles(htmlStyle, bodyStyle, zoom, padding, true)

                        // anim code
                        bodyStyle.transform = `scale(1) translate(0px 0px)`
                        bodyStyle.willChange = 'transform'
                        bodyStyle.transition = 'transform ease 0.5s, min-height ease 0.5s, height ease 0.5s'
                        bodyStyle.transformOrigin = `top left`

                        attachDockScrollListener(zoom, padding)
                    } else {
                        htmlStyle.background = 'auto'
                        bodyStyle.transform = 'none'
                        bodyStyle.willChange = 'unset'
                        removeDockScrollListener()
                    }
                })

                // 500ms later when we finished zooming in/out and the old element faded from the view
                await breakpoint(500)

                // Second tick.
                window.requestAnimationFrame(() => {
                    updateDockToolbarVariables(shadowRef, zoom, padding, sidebarWidth)
                    bodyStyle.overflow = 'auto'
                    if (mode !== 'dock') {
                        bodyStyle.width = `auto`
                        bodyStyle.minHeight = `auto`
                    }
                    mode === 'button' && actions.buttonAnimated()
                    mode === 'dock' && actions.dockAnimated()
                    mode === 'float' && actions.floatAnimated()
                    mode === '' && actions.hideButtonAnimated()
                })

                // 500ms later when it quieted down
                await breakpoint(500)

                // Third tick.
                window.requestAnimationFrame(() => {
                    updateDockToolbarVariables(shadowRef, zoom, padding, sidebarWidth)
                    mode === 'button' && actions.buttonFaded()
                    mode === 'dock' && actions.dockFaded()
                    mode === 'float' && actions.floatFaded()
                })
            }
        },
    }),
})
