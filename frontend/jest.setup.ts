import { configure } from '@testing-library/react'
import 'jest-canvas-mock'
import { TextDecoder, TextEncoder } from 'util'
import 'whatwg-fetch'

// Jest/JSDom don't know about TextEncoder but the browsers we support do
// https://github.com/jsdom/jsdom/issues/2524
global.TextDecoder = TextDecoder as any
global.TextEncoder = TextEncoder as any

window.scrollTo = jest.fn()
window.matchMedia = jest.fn(() => ({ matches: false, addListener: jest.fn(), removeListener: jest.fn() }) as any)

// we use CSS.escape in the toolbar, but Jest/JSDom doesn't support it
if (typeof (globalThis as any).CSS === 'undefined') {
    ;(globalThis as any).CSS = {}
}

if (typeof (globalThis as any).CSS.escape !== 'function') {
    ;(globalThis as any).CSS.escape = (value: string) => value
}

const mockIntersectionObserver = jest.fn()
mockIntersectionObserver.mockReturnValue({
    observe: () => null,
    unobserve: () => null,
    disconnect: () => null,
})
;(globalThis as any).IntersectionObserver = mockIntersectionObserver

// Tell React Testing Library to use "data-attr" as the test ID attribute
configure({ testIdAttribute: 'data-attr' })

// Mock DecompressionWorkerManager globally to avoid import.meta.url issues in tests
jest.mock('scenes/session-recordings/player/snapshot-processing/DecompressionWorkerManager')
