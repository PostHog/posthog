import '@testing-library/jest-dom'

import { act } from '@testing-library/react'
import * as React from 'react'
import { type Root, createRoot } from 'react-dom/client'

jest.mock('~/styles', () => ({}))

describe('render-query entry boot', () => {
    let hasOwnAtAppEvaluation: string
    let root: Root | undefined
    let documentListeners: jest.SpyInstance<void, Parameters<typeof document.addEventListener>>

    beforeEach(() => {
        jest.resetModules()
        hasOwnAtAppEvaluation = 'unknown'
        root = undefined
        document.body.innerHTML = '<div id="root"></div>'
        jest.spyOn(document, 'readyState', 'get').mockReturnValue('complete')
        documentListeners = jest.spyOn(document, 'addEventListener')
        jest.doMock('react', () => React)
        jest.doMock('react-dom/client', () => ({
            createRoot: (container: Element) => {
                root = createRoot(container)
                return root
            },
        }))
        jest.doMock('~/loadPostHogJS', () => ({ loadPostHogJS: jest.fn() }))
        jest.doMock('~/initKea', () => ({ initKea: jest.fn() }))
        jest.doMock('./RenderQueryApp', () => {
            hasOwnAtAppEvaluation = typeof Object.hasOwn
            return { RenderQueryApp: (): JSX.Element => <div data-attr="boot-test-render-query" /> }
        })
    })

    afterEach(async () => {
        for (const [type, listener, options] of documentListeners.mock.calls) {
            if (type === 'DOMContentLoaded') {
                document.removeEventListener(type, listener, options)
            }
        }
        await act(async () => root?.unmount())
        document.body.innerHTML = ''
        jest.restoreAllMocks()
    })

    it('shims Object.hasOwn before the render-query chunk evaluates on a pre-ES2022 engine', async () => {
        const nativeHasOwn = Object.hasOwn
        Reflect.deleteProperty(Object, 'hasOwn')

        try {
            await act(async () => {
                await jest.isolateModulesAsync(async () => {
                    await import('./index')
                })
            })

            expect(hasOwnAtAppEvaluation).toBe('function')
            expect(Object.hasOwn({ present: undefined }, 'present')).toBe(true)
            expect(Object.hasOwn({}, 'absent')).toBe(false)
            expect(document.querySelector('[data-attr="boot-test-render-query"]')).toBeInTheDocument()
        } finally {
            Object.defineProperty(Object, 'hasOwn', { value: nativeHasOwn, writable: true, configurable: true })
        }
    })
})
