import { kea } from 'kea'

// props:
// - shadowRef: shadowRoot ref
export const dockLogic = kea({
    // transition steps:
    // - dock: disabled, animating, fading, complete
    // - float: disabled, animating, fading, complete
    // call dock/float and it will start
    actions: () => ({
        // public
        dock: true,
        float: true,
        update: true,

        // private
        dockAnimated: true,
        floatAnimated: true,
        dockFaded: true,
        floatFaded: true,
        setMode: (mode, update = false) => ({ mode, update, windowWidth: window.innerWidth }),
    }),

    reducers: () => ({
        mode: [
            '',
            {
                dock: () => 'dock',
                float: () => 'float',
            },
        ],
        lastMode: [
            '',
            { persist: true },
            {
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
        dockStatus: [
            'disabled',
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
            'disabled',
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
            cache.listener = () => actions.update()
            window.addEventListener('scroll', cache.listener)
            window.addEventListener('resize', cache.listener)
            window.requestAnimationFrame(() => {
                if (values.lastMode === 'dock') {
                    actions.dock()
                } else if (values.lastMode === 'float') {
                    actions.float()
                } else {
                    // TODO: add button mode
                    actions.float()
                }
            })
        },
        beforeUnmount: () => {
            window.removeEventListener('scroll', cache.listener)
            window.removeEventListener('resize', cache.listener)
        },
    }),

    listeners: ({ actions, values, props }) => ({
        dock: () => actions.setMode('dock', false),
        float: () => actions.setMode('float', false),
        update: () => actions.setMode(values.mode, true),
        setMode: async ({ mode, update }, breakpoint) => {
            const { padding, sidebarWidth, zoom } = values
            const bodyStyle = window.document.body.style
            const htmlStyle = window.document.querySelector('html').style
            const shadowRef = props.shadowRef

            // const setToolbarZoom = toolbarStyle.setProperty('--zoom-out', zoom)
            function updateToolbar() {
                if (shadowRef?.current) {
                    const toolbarDiv = shadowRef.current.shadowRoot.getElementById('docked-toolbar')
                    if (toolbarDiv) {
                        toolbarDiv.style.setProperty('--zoom-out', zoom)
                        toolbarDiv.style.setProperty('--padding', `${padding}px`)
                        toolbarDiv.style.setProperty('--sidebar-width', `${sidebarWidth}px`)
                    }
                }
            }

            shadowRef?.current ? updateToolbar() : window.requestAnimationFrame(updateToolbar)

            function setDockStyles(zoom, deferTransform = false) {
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
                        setDockStyles(zoom, false)
                    })
                }
            } else {
                window.requestAnimationFrame(() => {
                    bodyStyle.overflow = 'hidden'
                    if (mode === 'dock') {
                        setDockStyles(zoom, true)

                        // anim code
                        bodyStyle.transform = `scale(1) translate(0px 0px)`
                        bodyStyle.willChange = 'transform'
                        bodyStyle.transition = 'transform ease 0.5s, min-height ease 0.5s, height ease 0.5s'
                        bodyStyle.transformOrigin = `top left`

                        attachScrollListener(zoom, padding)
                    } else {
                        htmlStyle.background = 'auto'
                        bodyStyle.transform = 'none'
                        bodyStyle.willChange = 'unset'
                        removeScrollListener()
                    }
                })

                // 500ms later when we finished zooming in/out and the old element faded from the view
                await breakpoint(500)
                window.requestAnimationFrame(() => {
                    updateToolbar()
                    bodyStyle.overflow = 'auto'
                    if (mode === 'float') {
                        bodyStyle.width = `auto`
                        bodyStyle.minHeight = `auto`
                    }
                    mode === 'dock' ? actions.dockAnimated() : actions.floatAnimated()
                })

                // 500ms later when it quieted down
                await breakpoint(500)
                window.requestAnimationFrame(() => {
                    updateToolbar()
                    mode === 'dock' ? actions.dockFaded() : actions.floatFaded()
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

    // window.addEventListener('scroll', function(e) {
    //   toolbar.shadowRoot.getElementById('toolbar').style.marginTop = `${window.pageYOffset / zoom}px`;
    // })
}

function removeScrollListener() {
    window.removeEventListener('scroll', listener)
}
