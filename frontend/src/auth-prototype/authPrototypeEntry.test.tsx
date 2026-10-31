import '@testing-library/jest-dom'

import { act } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import * as React from 'react'
import { createRoot, type Root } from 'react-dom/client'

jest.mock('~/styles', () => ({}))

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((resolvePromise) => {
        resolve = resolvePromise
    })
    return { promise, resolve }
}

describe('standalone login entry stylesheet gate', () => {
    const originalMark = Object.getOwnPropertyDescriptor(performance, 'mark')
    const initialUrl = window.location.href
    let root: Root
    let stylesheet: ReturnType<typeof deferred<boolean>>
    let reportBootFailure: jest.Mock
    let moduleReady: boolean
    let moduleGate: ReturnType<typeof deferred<void>>

    beforeEach(() => {
        jest.resetModules()
        jest.useFakeTimers()
        stylesheet = deferred<boolean>()
        moduleGate = deferred<void>()
        moduleReady = true
        reportBootFailure = jest.fn()
        window.ESBUILD_CSS_READY = stylesheet.promise
        const html = readFileSync(`${__dirname}/authPrototype.html`, 'utf8')
        document.body.innerHTML = html.match(/<body[^>]*>([\s\S]*?)<\/body>/)![1]
        const recoveryScript = document.querySelector('script')!.textContent!
        runInNewContext(recoveryScript, { window, document, setTimeout, URL })
        root = createRoot(document.getElementById('root')!)
        jest.spyOn(document, 'readyState', 'get').mockReturnValue('complete')
        Object.defineProperty(performance, 'mark', { configurable: true, value: jest.fn() })
        jest.doMock('react', () => React)
        jest.doMock('react-dom/client', () => ({ createRoot: () => root }))
        jest.doMock('../RootErrorBoundary', () => ({
            RootErrorBoundary: ({ children }: { children: React.ReactNode }) => children,
            reportBootFailure,
        }))
        jest.doMock('./AuthPrototype', () => ({
            AuthPrototype: () => {
                if (!moduleReady) {
                    throw moduleGate.promise
                }
                return (
                    <form>
                        Login form
                        <input aria-label="Email" />
                    </form>
                )
            },
        }))
        jest.doMock('../initKea', () => ({ initKea: jest.fn() }))
        jest.doMock('../loadPostHogJS', () => ({ loadPostHogJS: jest.fn() }))
    })

    afterEach(async () => {
        await act(async () => root.unmount())
        delete window.ESBUILD_CSS_READY
        window.history.replaceState(null, '', initialUrl)
        document.body.innerHTML = ''
        jest.clearAllTimers()
        jest.useRealTimers()
        jest.restoreAllMocks()
        if (originalMark) {
            Object.defineProperty(performance, 'mark', originalMark)
        } else {
            Reflect.deleteProperty(performance, 'mark')
        }
    })

    it.each([
        ['loads before the gate', true, 0],
        ['loads after the gate', true, 6000],
        ['fails before the gate', false, 0],
        ['fails after the gate', false, 6000],
    ])('%s', async (_case, loaded, delayMs) => {
        await act(async () => {
            await jest.isolateModulesAsync(async () => {
                await import('./authPrototypeEntry')
            })
        })

        if (delayMs) {
            await act(async () => {
                await jest.advanceTimersByTimeAsync(delayMs)
            })
        }
        expect(document.getElementById('root')!.querySelector('form') !== null).toBe(delayMs > 0)
        expect(reportBootFailure).not.toHaveBeenCalled()

        await act(async () => stylesheet.resolve(loaded))

        expect(document.getElementById('root')).toHaveTextContent(loaded ? 'Login form' : 'Login styles could not load')
        expect(document.querySelectorAll('a')).toHaveLength(1)
        expect(document.getElementById('login-entry-recovery')?.isConnected ?? false).toBe(loaded)
        expect(reportBootFailure).toHaveBeenCalledTimes(loaded ? 0 : 1)
    })

    it.each([false, true])(
        'keeps recovery connected while the module is pending after the CSS gate (%s)',
        async (cssReady) => {
            window.history.replaceState(null, '', '/login?next=%2Freset%3Ftoken%3Dexample#panel=support')
            runInNewContext(document.querySelector('script')!.textContent!, { window, document, setTimeout, URL })
            moduleReady = false
            await act(async () => {
                await jest.isolateModulesAsync(async () => {
                    await import('./authPrototypeEntry')
                })
            })
            if (cssReady) {
                await act(async () => stylesheet.resolve(true))
            }
            await act(async () => {
                await jest.advanceTimersByTimeAsync(5000)
            })

            const recovery = document.getElementById('login-entry-recovery') as HTMLAnchorElement
            expect(recovery.isConnected).toBe(true)
            expect(recovery.hidden).toBe(false)
            expect(recovery.href).toBe(
                `${window.location.origin}/login?next=%2Freset%3Ftoken%3Dexample&auth_app=fallback#panel=support`
            )

            moduleReady = true
            await act(async () => moduleGate.resolve())
            expect(document.getElementById('root')!.querySelector('form')).toBeInTheDocument()
        }
    )
})
