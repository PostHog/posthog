import '@testing-library/jest-dom'

import { act } from '@testing-library/react'
import * as React from 'react'
import { createRoot } from 'react-dom/client'

jest.mock('~/styles', () => ({}))

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

describe('app entry boot', () => {
    let modulesLoaded: string[]
    let bootApp: jest.Mock
    let stylesheet: ReturnType<typeof deferred<boolean>>
    let documentListeners: jest.SpyInstance<void, Parameters<typeof document.addEventListener>>

    beforeEach(() => {
        jest.resetModules()
        jest.useFakeTimers()
        modulesLoaded = []
        bootApp = jest.fn()
        stylesheet = deferred<boolean>()
        window.ESBUILD_CSS_READY = stylesheet.promise
        document.body.innerHTML = '<div id="root"></div>'
        window.__posthogAppRoot = createRoot(document.getElementById('root')!)
        jest.spyOn(document, 'readyState', 'get').mockReturnValue('complete')
        documentListeners = jest.spyOn(document, 'addEventListener')
        jest.doMock('react', () => React)
        jest.doMock('react-dom/client', () => ({ createRoot }))
        jest.doMock('scenes/App', () => {
            modulesLoaded.push('App')
            return {
                App: (): JSX.Element => {
                    if (bootApp.mock.calls.length !== 1) {
                        throw new Error('App rendered without one-time boot')
                    }
                    return <div data-attr="boot-test-app" />
                },
            }
        })
        jest.doMock('scenes/bootApp', () => {
            modulesLoaded.push('bootApp')
            return { bootApp }
        })
    })

    afterEach(async () => {
        for (const [type, listener, options] of documentListeners.mock.calls) {
            if (type === 'DOMContentLoaded') {
                document.removeEventListener(type, listener, options)
            }
        }
        await act(async () => window.__posthogAppRoot?.unmount())
        delete window.__posthogAppRoot
        delete window.ESBUILD_CSS_READY
        delete window.POSTHOG_USER_IDENTITY_WITH_FLAGS
        delete window.POSTHOG_APP_CONTEXT
        document.body.innerHTML = ''
        jest.clearAllTimers()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    async function loadEntry(): Promise<void> {
        await act(async () => {
            await jest.isolateModulesAsync(async () => {
                await import('./index')
            })
        })
    }

    describe.each([
        ['the lazy app path', false],
        ['the render as update path', true],
    ])('on %s', (_path, renderAppAsUpdate) => {
        beforeEach(() => {
            window.POSTHOG_USER_IDENTITY_WITH_FLAGS = {
                featureFlags: { 'boot-render-app-as-update': renderAppAsUpdate },
            }
        })

        it.each(['complete', 'loading'] as const)(
            'loads modules while CSS is pending after the document is %s',
            async (readyState) => {
                const documentState = jest.spyOn(document, 'readyState', 'get').mockReturnValue(readyState)
                await loadEntry()

                expect(modulesLoaded).toEqual(readyState === 'complete' ? ['App', 'bootApp'] : [])
                if (readyState === 'loading') {
                    documentState.mockReturnValue('complete')
                    await act(async () => {
                        document.dispatchEvent(new Event('DOMContentLoaded'))
                    })
                }

                expect(modulesLoaded).toEqual(['App', 'bootApp'])
                expect(bootApp).not.toHaveBeenCalled()
                expect(document.getElementById('root')).toBeEmptyDOMElement()

                await act(async () => stylesheet.resolve(true))

                expect(document.querySelector('[data-attr="boot-test-app"]')).toBeInTheDocument()
                expect(bootApp).toHaveBeenCalledTimes(1)
            }
        )

        it.each(['loaded', 'absent'] as const)('boots when the stylesheet is %s', async (stylesheetState) => {
            if (stylesheetState === 'absent') {
                delete window.ESBUILD_CSS_READY
            }
            await loadEntry()

            await act(async () => {
                if (stylesheetState === 'loaded') {
                    stylesheet.resolve(true)
                }
            })

            expect(document.querySelector('[data-attr="boot-test-app"]')).toBeInTheDocument()
            expect(bootApp).toHaveBeenCalledTimes(1)
        })

        it.each([
            ['within the render gate', 0],
            ['after a stall let the app render', 6000],
        ])('offers a reload instead of an unstyled app when every stylesheet URL fails %s', async (_case, stallMs) => {
            await loadEntry()
            await act(async () => {
                await jest.advanceTimersByTimeAsync(stallMs)
            })

            await act(async () => stylesheet.resolve(false))

            expect(document.querySelector('[role="alert"]')).toHaveTextContent('PostHog failed to load its styles.')
            expect(document.querySelector('[data-attr="boot-test-app"]')).not.toBeInTheDocument()
        })

        it('boots after five seconds if the stylesheet stays pending', async () => {
            await loadEntry()
            await act(async () => {
                await jest.advanceTimersByTimeAsync(4999)
            })
            expect(bootApp).not.toHaveBeenCalled()
            expect(document.getElementById('root')).toBeEmptyDOMElement()

            await act(async () => {
                await jest.advanceTimersByTimeAsync(1)
            })
            expect(document.querySelector('[data-attr="boot-test-app"]')).toBeInTheDocument()
            expect(bootApp).toHaveBeenCalledTimes(1)
        })

        if (renderAppAsUpdate) {
            it('preloads the authenticated shell for a logged-in user before App renders', async () => {
                window.POSTHOG_APP_CONTEXT = { current_user: { id: 1 } } as any
                const loadOrder: string[] = []
                const loadAuthenticatedShell = jest.fn(async () => {
                    loadOrder.push('shell')
                })
                jest.doMock('scenes/authenticatedShellLoader', () => ({ loadAuthenticatedShell }))
                jest.doMock('scenes/App', () => ({
                    App: (): JSX.Element => {
                        loadOrder.push('app-rendered')
                        return <div data-attr="boot-test-app" />
                    },
                }))

                await loadEntry()
                await act(async () => stylesheet.resolve(true))

                expect(loadAuthenticatedShell).toHaveBeenCalledTimes(1)
                expect(loadOrder).toEqual(['shell', 'app-rendered'])
                expect(document.querySelector('[data-attr="boot-test-app"]')).toBeInTheDocument()
            })
        }

        it.each(['scenes/App', 'scenes/bootApp'])(
            'shows an early %s failure through the boot error boundary after CSS is ready',
            async (failingModule) => {
                jest.spyOn(console, 'error').mockImplementation(() => {})
                const error = new Error('Boot dependency failed')
                jest.doMock(failingModule, () => {
                    throw error
                })

                await loadEntry()
                await act(async () => {
                    await jest.advanceTimersByTimeAsync(0)
                })
                expect(document.getElementById('root')).toBeEmptyDOMElement()
                expect(bootApp).not.toHaveBeenCalled()

                await act(async () => stylesheet.resolve(true))

                expect(document.querySelector('[role="alert"]')).toHaveTextContent('PostHog crashed while starting.')
                expect(bootApp).not.toHaveBeenCalled()
            }
        )
    })

    it('commits the app without waiting for the suspense fallback throttle when a child suspends', async () => {
        // React skips the throttle inside act(), so this case renders without it.
        // React captures setTimeout when it loads, so load it again under the fake timers for the throttle to use them.
        await act(async () => window.__posthogAppRoot?.unmount())
        const fakeTimerReactDom = jest.requireActual<typeof import('react-dom/client')>('react-dom/client')
        jest.doMock('react-dom/client', () => fakeTimerReactDom)
        window.__posthogAppRoot = fakeTimerReactDom.createRoot(document.getElementById('root')!)
        const reactActEnvironment = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }
        const previousActEnvironment = reactActEnvironment.IS_REACT_ACT_ENVIRONMENT
        reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = false
        const NeverLoads = React.lazy(() => new Promise<{ default: React.ComponentType }>(() => {}))
        jest.doMock('scenes/App', () => ({
            App: (): JSX.Element => (
                <React.Suspense fallback={<div data-attr="boot-test-shell-fallback" />}>
                    <NeverLoads />
                </React.Suspense>
            ),
        }))
        window.POSTHOG_USER_IDENTITY_WITH_FLAGS = { featureFlags: { 'boot-render-app-as-update': true } }
        try {
            await jest.isolateModulesAsync(async () => {
                await import('./index')
            })
            stylesheet.resolve(true)
            await jest.advanceTimersByTimeAsync(100)

            expect(document.querySelector('[data-attr="boot-test-shell-fallback"]')).toBeInTheDocument()
        } finally {
            reactActEnvironment.IS_REACT_ACT_ENVIRONMENT = previousActEnvironment
        }
    })
})
