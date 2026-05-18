import 'jest-canvas-mock'
import 'whatwg-fetch'

import { configure } from '@testing-library/react'
import { TextDecoder, TextEncoder } from 'util'

// Jest/JSDom don't know about TextEncoder but the browsers we support do
// https://github.com/jsdom/jsdom/issues/2524
global.TextDecoder = TextDecoder as any
global.TextEncoder = TextEncoder as any

window.scrollTo = jest.fn()
window.matchMedia = jest.fn(
    (query: string) =>
        ({
            matches: false,
            media: query,
            onchange: null,
            addListener: jest.fn(),
            removeListener: jest.fn(),
            addEventListener: jest.fn(),
            removeEventListener: jest.fn(),
            dispatchEvent: jest.fn(),
        }) as any
)

type StorageLike = {
    getItem: (key: string) => string | null
    setItem: (key: string, value: string) => void
    removeItem: (key: string) => void
    clear: () => void
}

const createInMemoryStorage = (): StorageLike => {
    const store = new Map<string, string>()
    return {
        getItem: (key) => (store.has(key) ? store.get(key)! : null),
        setItem: (key, value) => {
            store.set(key, String(value))
        },
        removeItem: (key) => {
            store.delete(key)
        },
        clear: () => {
            store.clear()
        },
    }
}

// Some Jest/JSDom environments might not provide an unqualified `sessionStorage`
// binding. `sceneLogic` and other Kea logic reference `sessionStorage` as a
// free variable, so we need to ensure the identifier exists.
if (typeof sessionStorage === 'undefined') {
    const sessionStorageStub = createInMemoryStorage()
    ;(globalThis as any).sessionStorage = sessionStorageStub
    ;(window as any).sessionStorage = sessionStorageStub
    ;(global as any).sessionStorage = sessionStorageStub
}

if (typeof localStorage === 'undefined') {
    const localStorageStub = createInMemoryStorage()
    ;(globalThis as any).localStorage = localStorageStub
    ;(window as any).localStorage = localStorageStub
    ;(global as any).localStorage = localStorageStub
}

// jsdom does not implement AbortSignal.timeout — polyfill for tests
if (typeof AbortSignal.timeout !== 'function') {
    AbortSignal.timeout = (ms: number): AbortSignal => {
        const controller = new AbortController()
        setTimeout(() => controller.abort(new DOMException('TimeoutError', 'TimeoutError')), ms)
        return controller.signal
    }
}

// Base UI's ScrollArea calls getAnimations() which jsdom doesn't support
if (typeof Element.prototype.getAnimations !== 'function') {
    Element.prototype.getAnimations = () => []
}

// LemonMenu calls scrollIntoView which jsdom doesn't support
if (typeof Element.prototype.scrollIntoView !== 'function') {
    Element.prototype.scrollIntoView = () => {}
}

// maplibre-gl probes window.URL.createObjectURL at module-eval time, but jsdom
// doesn't implement it. Provide a noop so importing modules that transitively
// pull in maplibre-gl (e.g. NotebookNodeMap) doesn't throw.
if (typeof window !== 'undefined' && typeof window.URL.createObjectURL !== 'function') {
    window.URL.createObjectURL = () => ''
    window.URL.revokeObjectURL = () => {}
}

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

// Mock posthog-js surveys-preview to avoid ESM import issues in tests
jest.mock('posthog-js/dist/surveys-preview', () => ({
    renderFeedbackWidgetPreview: jest.fn(),
    renderSurveysPreview: jest.fn(),
    getNextSurveyStep: jest.fn(),
}))

// Mock posthog-js product-tours-preview to avoid ESM import issues in tests
jest.mock('posthog-js/dist/product-tours-preview', () => ({
    renderProductTourPreview: jest.fn(),
}))

// Mock posthog-js element-inference to avoid ESM import issues in tests
jest.mock('posthog-js/dist/element-inference', () => ({
    findElement: jest.fn(),
    getElementPath: jest.fn(),
}))

// Mock posthog-js to avoid issues in tests
jest.mock('posthog-js', () => {
    // Get the actual module to preserve type exports (enums, etc.)
    const actual = jest.requireActual('posthog-js')

    const mock: Record<string, any> = {
        capture: jest.fn(),
        captureException: jest.fn(),
        captureRaw: jest.fn(),
        opt_in_capturing: jest.fn(),
        identify: jest.fn(),
        getFeatureFlag: jest.fn(),
        getFeatureFlagPayload: jest.fn(),
        getAllFlags: jest.fn(),
        isFeatureEnabled: jest.fn(),
        getEarlyAccessFeatures: jest.fn(),
        getSurveys: jest.fn(),
        onFeatureFlags: jest.fn(() => () => {}),
        debug: jest.fn(),
        get_session_id: jest.fn(),
        get_session_replay_url: jest.fn(),
        get_distinct_id: jest.fn(),
        register: jest.fn(),
        reset: jest.fn(),
        group: jest.fn(),
        updateEarlyAccessFeatureEnrollment: jest.fn(),
        people: { set: jest.fn() },
        featureFlags: { override: jest.fn() },
    }
    mock.init = jest.fn(() => mock)

    // Return mock functions but preserve actual type exports
    return { ...actual, __esModule: true, default: mock, posthog: mock }
})

jest.mock('@tiptap/extension-code-block-lowlight', () => {
    const mockExtension = {
        configure: jest.fn(() => ({})),
        extend: jest.fn(() => ({
            configure: jest.fn(() => ({})),
        })),
    }
    return {
        __esModule: true,
        default: mockExtension,
        CodeBlockLowlight: mockExtension,
    }
})
