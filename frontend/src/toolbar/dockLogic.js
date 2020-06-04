import { kea } from 'kea'

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
        update: true,
        setNextOpenMode: mode => ({ mode }),

        // private
        buttonAnimated: true,
        buttonFaded: true,
        dockAnimated: true,
        dockFaded: true,
        floatAnimated: true,
        floatFaded: true,
        setMode: (mode, update = false) => ({ mode, update, windowWidth: window.innerWidth }),
    }),

    reducers: () => ({
        mode: [
            '',
            {
                button: () => 'button',
                dock: () => 'dock',
                float: () => 'float',
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
        nextOpenMode: [
            'dock',
            { persist: true },
            {
                dock: () => 'dock',
                float: () => 'float',
                setNextOpenMode: (_, { mode }) => mode,
            },
        ],
        windowWidth: [
            -1,
            {
                setMode: (_, { windowWidth }) => windowWidth,
            },
        ],
        dockStatus: [
            'disabled',
            {
                dock: () => 'animating',
                dockAnimated: () => 'fading-in',
                dockFaded: () => 'complete',

                float: () => 'fading-out',
                floatAnimated: () => 'disabled',
                floatFaded: () => 'disabled',
                button: () => 'fading-out',
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

                button: () => 'fading-out',
                buttonAnimated: () => 'disabled',
                buttonFaded: () => 'disabled',
                dock: () => 'fading-out',
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

                dock: () => 'fading-out',
                dockAnimated: () => 'disabled',
                dockFaded: () => 'disabled',
                float: () => 'fading-out',
                floatAnimated: () => 'disabled',
                floatFaded: () => 'disabled',
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        sidebarWidth: [() => [], () => 300],
        padding: [
            () => [selectors.mode, selectors.windowWidth],
            (mode, windowWidth) =>
                mode === 'dock' ? (windowWidth > 1200 ? Math.min(30 + (windowWidth - 1200) * 0.3, 60) : 30) : 0,
        ],
        bodyWidth: [
            () => [selectors.mode, selectors.windowWidth, selectors.sidebarWidth, selectors.padding],
            (mode, windowWidth, sidebarWidth, padding) =>
                mode === 'dock' ? windowWidth - sidebarWidth - 3 * padding : windowWidth,
        ],
        zoom: [() => [selectors.bodyWidth, selectors.windowWidth], (bodyWidth, windowWidth) => bodyWidth / windowWidth],
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
                } else if (values.lastMode === 'button') {
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
        update: () => actions.setMode(values.mode, true),
        setMode: async ({ mode, update }, breakpoint) => {
            const { padding, sidebarWidth, zoom } = values
            const bodyStyle = window.document.body.style
            const htmlStyle = window.document.querySelector('html').style
            const shadowRef = props.shadowRef

            function updateDockToolbarVariables() {
                if (shadowRef?.current) {
                    const toolbarDiv = shadowRef.current.shadowRoot.getElementById('dock-toolbar')
                    if (toolbarDiv) {
                        toolbarDiv.style.setProperty('--zoom-out', zoom)
                        toolbarDiv.style.setProperty('--padding', `${padding}px`)
                        toolbarDiv.style.setProperty('--sidebar-width', `${sidebarWidth}px`)
                    }
                }
            }

            shadowRef?.current ? updateDockToolbarVariables() : window.requestAnimationFrame(updateDockToolbarVariables)

            function setDockBodyStyles(deferTransform = false) {
                // dark mode:
                // htmlStyle.background = 'hsl(231, 17%, 22%)'
                htmlStyle.background =
                    'linear-gradient(to right, hsla(234, 17%, 94%, 1) 71%, hsla(234, 17%, 99%, 1) 100%)'
                bodyStyle.boxShadow = 'hsl(219, 14%, 76%) 30px 30px 70px, hsl(219, 14%, 76%) 8px 8px 10px'
                if (!bodyStyle.backgroundColor) {
                    bodyStyle.backgroundColor = 'white'
                }
                bodyStyle.width = `100vw`
                bodyStyle.height = `auto`
                bodyStyle.minHeight = `calc(${100 / zoom}% - ${(2 * padding) / zoom}px)`

                if (deferTransform) {
                    // needed by the animation
                    window.requestAnimationFrame(() => {
                        bodyStyle.transform = `scale(${zoom}) translate(${padding / zoom}px, ${padding / zoom}px)`
                    })
                } else {
                    bodyStyle.transform = `scale(${zoom}) translate(${padding / zoom}px, ${padding / zoom}px)`
                }
            }

            if (update) {
                if (mode === 'dock') {
                    window.requestAnimationFrame(() => {
                        setDockBodyStyles(false)
                    })
                }
            } else {
                window.requestAnimationFrame(() => {
                    bodyStyle.overflow = 'hidden'
                    if (mode === 'dock') {
                        setDockBodyStyles(true)

                        // anim code
                        bodyStyle.transform = `scale(1) translate(0px 0px)`
                        bodyStyle.willChange = 'transform'
                        bodyStyle.transition = 'transform ease 0.5s, min-height ease 0.5s, height ease 0.5s'
                        bodyStyle.transformOrigin = `top left`

                        attachScrollListener(zoom, padding)
                    } else if (mode === 'float' || mode === 'button') {
                        htmlStyle.background = 'auto'
                        bodyStyle.transform = 'none'
                        bodyStyle.willChange = 'unset'
                        removeScrollListener()
                    }
                })

                // 500ms later when we finished zooming in/out and the old element faded from the view
                await breakpoint(500)
                window.requestAnimationFrame(() => {
                    updateDockToolbarVariables()
                    bodyStyle.overflow = 'auto'
                    if (mode === 'float' || mode === 'button') {
                        bodyStyle.width = `auto`
                        bodyStyle.minHeight = `auto`
                    }
                    mode === 'button' && actions.buttonAnimated()
                    mode === 'dock' && actions.dockAnimated()
                    mode === 'float' && actions.floatAnimated()
                })

                // 500ms later when it quieted down
                await breakpoint(500)
                window.requestAnimationFrame(() => {
                    updateDockToolbarVariables()
                    mode === 'button' && actions.buttonFaded()
                    mode === 'dock' && actions.dockFaded()
                    mode === 'float' && actions.floatFaded()
                })
            }
        },
    }),
})

let listener
function attachScrollListener(zoom, padding) {
    listener = function() {
        const bodyElements = [...document.body.getElementsByTagName('*')]
        bodyElements
            .filter(x => getComputedStyle(x, null).getPropertyValue('position') === 'fixed')
            .forEach(e => {
                const h = (window.pageYOffset + (window.pageYOffset > padding ? -padding : 0)) / zoom
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
}

function removeScrollListener() {
    window.removeEventListener('scroll', listener)
}
