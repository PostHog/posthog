import { kea } from 'kea'
import {
    attachDockScrollListener,
    removeDockScrollListener,
    applyDockBodyStyles,
    updateDockToolbarVariables,
} from '~/toolbar/dockUtils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'

// props:
// - shadowRef: shadowRoot ref
export const dockLogic = kea({
    props: {
        shadowRef: 'required',
        padding: 'optional',
    },

    // transition steps:
    // - dock: disabled, animating, fading, complete
    // - button: disabled, animating, fading, complete
    // call dock/button and it will start
    actions: () => ({
        // public
        button: true,
        dock: true,
        hideButton: true,
        update: true,

        // private
        buttonAnimated: true,
        buttonFaded: true,
        dockAnimated: true,
        dockFaded: true,
        hideButtonAnimated: true,
        setMode: (mode, update = false) => ({
            mode,
            update,
            windowWidth: window.innerWidth,
            windowHeight: window.innerHeight,
        }),
    }),

    windowValues: {
        windowWidth: window => window.innerWidth,
        windowHeight: window => window.innerHeight,
    },

    reducers: () => ({
        mode: [
            '',
            {
                setMode: (_, { mode }) => mode,
            },
        ],
        lastMode: [
            '',
            { persist: true },
            {
                button: () => 'button',
                dock: () => 'dock',
            },
        ],
        dockStatus: [
            'disabled',
            {
                dock: () => 'animating',
                dockAnimated: () => 'fading-in',
                dockFaded: () => 'complete',

                button: state => (state === 'disabled' ? 'disabled' : 'fading-out'),
                buttonAnimated: () => 'disabled',
                buttonFaded: () => 'disabled',
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

                hideButton: state => (state === 'disabled' ? 'disabled' : 'fading-out'),
                hideButtonAnimated: () => 'disabled',
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        isAnimating: [
            () => [selectors.dockStatus, selectors.buttonStatus],
            (dockStatus, buttonStatus) => !![dockStatus, buttonStatus].find(s => s === 'animating'),
        ],
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

        domZoom: [() => [selectors.zoom, selectors.mode], (zoom, mode) => (mode === 'dock' ? zoom : 1)],
        domPadding: [() => [selectors.padding, selectors.mode], (padding, mode) => (mode === 'dock' ? padding : 0)],
    }),

    events: ({ cache, actions, values }) => ({
        afterMount: () => {
            window.__POSTHOG_SET_MODE__ = actions.setMode // export this for debugging in case it goes wrong client side
            cache.onScrollResize = () => actions.update()
            window.addEventListener('scroll', cache.onScrollResize)
            window.addEventListener('resize', cache.onScrollResize)
            window.requestAnimationFrame(() => {
                if (toolbarLogic.values.isAuthenticated) {
                    if (values.lastMode === 'dock') {
                        actions.dock()
                    } else {
                        actions.button()
                    }
                } else {
                    actions.button()
                }
            })
        },
        beforeUnmount: () => {
            window.removeEventListener('scroll', cache.onScrollResize)
            window.removeEventListener('resize', cache.onScrollResize)
        },
    }),

    listeners: ({ actions, values, props }) => ({
        button: () => {
            values.mode !== 'button' && actions.setMode('button', false)
        },
        dock: () => {
            values.mode !== 'dock' && actions.setMode('dock', false)
        },
        hideButton: () => {
            values.mode !== '' && actions.setMode('', false)
        },
        update: () => {
            values.mode !== '' && !values.isAnimating && actions.setMode(values.mode, true)
        },
        setMode: async ({ mode, update }, breakpoint) => {
            const { padding, sidebarWidth, zoom } = values
            const bodyStyle = window.document.body.style
            const htmlStyle = window.document.querySelector('html').style
            const shadowRef = props.shadowRef

            // Update CSS variables (--zoom, etc) in #dock-toolbar inside the shadow root
            shadowRef?.current
                ? updateDockToolbarVariables(shadowRef, zoom, padding, sidebarWidth)
                : window.requestAnimationFrame(() => updateDockToolbarVariables(shadowRef, zoom, padding, sidebarWidth))

            // if update (scroll, resize) vs toggle between button<->dock
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
                    bodyStyle.overflow = 'visible'
                    if (mode !== 'dock') {
                        bodyStyle.width = `auto`
                        bodyStyle.minHeight = `auto`
                    }
                    mode === 'button' && actions.buttonAnimated()
                    mode === 'dock' && actions.dockAnimated()
                    mode === '' && actions.hideButtonAnimated()
                })

                // 500ms later when it quieted down
                await breakpoint(500)

                // Third tick.
                window.requestAnimationFrame(() => {
                    if (mode === 'dock') {
                        bodyStyle.overflow = 'visible'
                    }
                    updateDockToolbarVariables(shadowRef, zoom, padding, sidebarWidth)
                    mode === 'button' && actions.buttonFaded()
                    mode === 'dock' && actions.dockFaded()
                })
            }
        },
    }),
})
