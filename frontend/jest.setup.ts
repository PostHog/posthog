import 'whatwg-fetch'
import 'jest-canvas-mock'

import { configure } from '@testing-library/react'
import { TextDecoder, TextEncoder } from 'util'

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

// Tell React Testing Library to use "data-attr" as the test ID attribute
configure({ testIdAttribute: 'data-attr' })