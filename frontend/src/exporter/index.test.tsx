import '@testing-library/jest-dom'

import { act } from '@testing-library/react'
import * as React from 'react'
import { type Root, createRoot } from 'react-dom/client'

import { ExportType } from '~/exporter/types'

jest.mock('~/styles', () => ({}))

describe('exporter entry boot', () => {
    let hasOwnAtExporterEvaluation: string
    let root: Root | undefined
    let documentListeners: jest.SpyInstance<void, Parameters<typeof document.addEventListener>>

    beforeEach(() => {
        jest.resetModules()
        hasOwnAtExporterEvaluation = 'unknown'
        root = undefined
        document.body.innerHTML = '<div id="root"></div>'
        window.POSTHOG_EXPORTED_DATA = { type: ExportType.Embed }
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
        jest.doMock('lib/countryFlagEmojiPolyfill', () => ({ polyfillCountryFlags: jest.fn() }))
        jest.doMock('~/exporter/Exporter', () => {
            hasOwnAtExporterEvaluation = typeof Object.hasOwn
            return { Exporter: (): JSX.Element => <div data-attr="boot-test-exporter" /> }
        })
    })

    afterEach(async () => {
        for (const [type, listener, options] of documentListeners.mock.calls) {
            if (type === 'DOMContentLoaded') {
                document.removeEventListener(type, listener, options)
            }
        }
        await act(async () => root?.unmount())
        delete (window as { POSTHOG_EXPORTED_DATA?: unknown }).POSTHOG_EXPORTED_DATA
        document.body.innerHTML = ''
        jest.restoreAllMocks()
    })

    it('shims Object.hasOwn before the exporter chunk evaluates on a pre-ES2022 engine', async () => {
        const nativeHasOwn = Object.hasOwn
        Reflect.deleteProperty(Object, 'hasOwn')

        try {
            await act(async () => {
                await jest.isolateModulesAsync(async () => {
                    await import('./index')
                })
            })

            expect(hasOwnAtExporterEvaluation).toBe('function')
            expect(Object.hasOwn({ present: undefined }, 'present')).toBe(true)
            expect(Object.hasOwn({}, 'absent')).toBe(false)
            expect(document.querySelector('[data-attr="boot-test-exporter"]')).toBeInTheDocument()
        } finally {
            Object.defineProperty(Object, 'hasOwn', { value: nativeHasOwn, writable: true, configurable: true })
        }
    })
})
