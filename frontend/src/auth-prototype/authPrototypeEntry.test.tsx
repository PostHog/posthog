import '@testing-library/jest-dom'

import { act } from '@testing-library/react'
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
    let root: Root
    let stylesheet: ReturnType<typeof deferred<boolean>>
    let reportBootFailure: jest.Mock

    beforeEach(() => {
        jest.resetModules()
        jest.useFakeTimers()
        stylesheet = deferred<boolean>()
        reportBootFailure = jest.fn()
        window.ESBUILD_CSS_READY = stylesheet.promise
        document.body.innerHTML = '<div id="root"></div>'
        root = createRoot(document.getElementById('root')!)
        jest.spyOn(document, 'readyState', 'get').mockReturnValue('complete')
        Object.defineProperty(performance, 'mark', { configurable: true, value: jest.fn() })
        jest.doMock('react', () => React)
        jest.doMock('react-dom/client', () => ({ createRoot: () => root }))
        jest.doMock('../RootErrorBoundary', () => ({
            RootErrorBoundary: ({ children }: { children: React.ReactNode }) => children,
            reportBootFailure,
        }))
        jest.doMock('./AuthPrototype', () => ({ AuthPrototype: () => <div>Login form</div> }))
        jest.doMock('../initKea', () => ({ initKea: jest.fn() }))
        jest.doMock('../loadPostHogJS', () => ({ loadPostHogJS: jest.fn() }))
    })

    afterEach(async () => {
        await act(async () => root.unmount())
        delete window.ESBUILD_CSS_READY
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
            expect(document.getElementById('root')).toHaveTextContent('Login form')
            expect(reportBootFailure).not.toHaveBeenCalled()
        }

        await act(async () => stylesheet.resolve(loaded))

        if (loaded) {
            expect(document.getElementById('root')).toHaveTextContent('Login form')
            expect(reportBootFailure).not.toHaveBeenCalled()
        } else {
            expect(document.getElementById('root')).toHaveTextContent('Login styles could not load')
            expect(reportBootFailure).toHaveBeenCalledTimes(1)
        }
    })
})
