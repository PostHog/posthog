// props:
// - mode: 'dock' | 'zoom'
import { kea } from 'kea'

export const dockLogic = kea({
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
            { persist: true },
            {
                dock: () => true,
                float: () => false,
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

    listeners: ({ sharedListeners }) => ({
        dock: sharedListeners.setMode,
        float: sharedListeners.setMode,
    }),

    events: ({ actions, values }) => ({
        afterMount: () => {
            if (values.docked) {
                actions.dock()
            } else {
                actions.float()
            }
        },
    }),

    sharedListeners: ({ actions }) => ({
        setMode: async ({ mode }, breakpoint) => {
            const zoom = 0.7

            window.requestAnimationFrame(() => {
                window.document.body.style.overflow = 'hidden'
                if (mode === 'dock') {
                    window.document.querySelector('html').style.background = 'hsl(231, 17%, 22%)'
                    window.document.body.style.transform = `scale(1) translate(0px 0px)`
                    window.document.body.style.willChange = 'transform'
                    window.document.body.style.transition =
                        'transform ease 0.5s, min-height ease 0.5s, height ease 0.5s'
                    window.document.body.style.transformOrigin = `top left`
                    window.document.body.style.width = `100vw`
                    window.document.body.style.height = `auto`
                    window.document.body.style.minHeight = `calc(${100 / zoom}% - ${40 / zoom}px)`
                    if (!window.document.body.style.backgroundColor) {
                        window.document.body.style.backgroundColor = 'white'
                    }
                    window.requestAnimationFrame(() => {
                        window.document.body.style.transform = `scale(${zoom}) translate(${20 / zoom}px, ${20 /
                            zoom}px)`
                    })
                    attachScrollListener(zoom)
                } else {
                    window.document.querySelector('html').style.background = 'auto'
                    window.document.body.style.transform = 'none'
                    window.document.body.style.willChange = 'unset'
                    removeScrollListener()
                }
            })

            await breakpoint(500)
            window.requestAnimationFrame(() => {
                window.document.body.style.overflow = 'auto'
                if (mode === 'float') {
                    window.document.body.style.width = `auto`
                    window.document.body.style.minHeight = `auto`
                }
                mode === 'dock' ? actions.dockAnimated() : actions.floatAnimated()
            })

            await breakpoint(500)
            window.requestAnimationFrame(() => {
                mode === 'dock' ? actions.dockFaded() : actions.floatFaded()
            })
        },
    }),
})

let listener
function attachScrollListener(zoom = 0.7) {
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

    // window.addEventListener('scroll', function(e) {
    //   toolbar.shadowRoot.getElementById('toolbar').style.marginTop = `${window.pageYOffset / zoom}px`;
    // })
}

function removeScrollListener() {
    window.removeEventListener('scroll', listener)
}
