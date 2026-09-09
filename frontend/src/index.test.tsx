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
    let configured: boolean
    let modulesLoaded: string[]
    let bootApp: jest.Mock
    let stylesheet: ReturnType<typeof deferred<boolean>>
    let documentListeners: jest.SpyInstance<void, Parameters<typeof document.addEventListener>>

    beforeEach(() => {
        jest.resetModules()
        jest.useFakeTimers()
        configured = false
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
        jest.doMock('lib/configureZod', () => {
            configured = true
            return {}
        })
        jest.doMock('scenes/App', () => {
            if (!configured) {
                throw new Error('App evaluated before Zod configuration')
            }
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
            if (!configured) {
                throw new Error('bootApp evaluated before Zod configuration')
            }
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

    it.each(['complete', 'loading'] as const)(
        'loads modules while CSS is pending after the document is %s',
        async (readyState) => {
            const documentState = jest.spyOn(document, 'readyState', 'get').mockReturnValue(readyState)
            await loadEntry()

            expect(configured).toBe(readyState === 'complete')
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

    it.each(['loaded', 'failed', 'absent'] as const)('boots when the stylesheet is %s', async (stylesheetState) => {
        if (stylesheetState === 'absent') {
            delete window.ESBUILD_CSS_READY
        }
        await loadEntry()

        await act(async () => {
            if (stylesheetState === 'loaded' || stylesheetState === 'failed') {
                stylesheet.resolve(stylesheetState === 'loaded')
            }
        })

        expect(document.querySelector('[data-attr="boot-test-app"]')).toBeInTheDocument()
        expect(bootApp).toHaveBeenCalledTimes(1)
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

    it.each(['configuration', 'module'] as const)(
        'shows an early %s failure through the boot error boundary after CSS is ready',
        async (failureStage) => {
            jest.spyOn(console, 'error').mockImplementation(() => {})
            const error = new Error('Boot dependency failed')
            if (failureStage === 'configuration') {
                jest.doMock('lib/configureZod', () => {
                    throw error
                })
            } else {
                jest.doMock('scenes/App', () => {
                    throw error
                })
            }

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
