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
    let sendBeacon: jest.Mock

    beforeEach(() => {
        jest.resetModules()
        jest.useFakeTimers()
        sendBeacon = jest.fn().mockReturnValue(true)
        Object.defineProperty(navigator, 'sendBeacon', { value: sendBeacon, configurable: true })
        window.JS_POSTHOG_API_KEY = 'test-api-key'
        window.JS_POSTHOG_HOST = 'https://us.example.com'
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
        delete window.POSTHOG_APP_CONTEXT_REQUEST
        delete window.JS_POSTHOG_API_KEY
        delete window.JS_POSTHOG_HOST
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

    it('loads modules while the user data is pending and boots once it arrives', async () => {
        const userData = deferred<{ app_context: object; feature_flags: null }>()
        window.POSTHOG_APP_CONTEXT_REQUEST = userData.promise
        await loadEntry()
        await act(async () => stylesheet.resolve(true))

        expect(modulesLoaded).toEqual(['App', 'bootApp'])
        expect(bootApp).not.toHaveBeenCalled()

        await act(async () => userData.resolve({ app_context: {}, feature_flags: null }))

        expect(document.querySelector('[data-attr="boot-test-app"]')).toBeInTheDocument()
        expect(bootApp).toHaveBeenCalledTimes(1)
    })

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
        expect(sendBeacon).not.toHaveBeenCalled()
    })

    it.each([
        [0, 'enabled'],
        [6000, 'enabled'],
        [0, 'opted-out'],
        [6000, 'opted-out'],
        [0, 'throws'],
        [6000, 'throws'],
    ] as const)('reports a terminal stylesheet failure after %i ms with capture %s', async (stallMs, capture) => {
        if (capture === 'opted-out') {
            delete window.JS_POSTHOG_API_KEY
        } else if (capture === 'throws') {
            sendBeacon.mockImplementation(() => {
                throw new Error('Transport unavailable')
            })
        }
        await loadEntry()
        await act(async () => {
            await jest.advanceTimersByTimeAsync(stallMs)
        })
        expect(sendBeacon).not.toHaveBeenCalled()

        await act(async () => stylesheet.resolve(false))

        expect(document.querySelector('[role="alert"]')).toHaveTextContent('PostHog failed to load its styles.')
        expect(document.querySelector('[data-attr="boot-test-app"]')).not.toBeInTheDocument()
        expect(sendBeacon).toHaveBeenCalledTimes(capture === 'opted-out' ? 0 : 1)
        const reports = sendBeacon.mock.calls.map(([url, body]) => ({ url, ...JSON.parse(body) }))
        expect(reports).toMatchObject(
            capture === 'opted-out'
                ? []
                : [
                      {
                          url: 'https://us.example.com/e/',
                          api_key: 'test-api-key',
                          event: '$exception',
                          properties: {
                              $process_person_profile: false,
                              $exception_level: 'fatal',
                              $exception_list: [
                                  { type: 'StylesheetLoadError', value: 'App stylesheet failed after all retries' },
                              ],
                              chunk_load_error: false,
                          },
                      },
                  ]
        )
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
        expect(sendBeacon).not.toHaveBeenCalled()
    })

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
