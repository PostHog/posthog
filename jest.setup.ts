import 'whatwg-fetch'
import 'jest-canvas-mock'

import { TextEncoder, TextDecoder } from 'util'
// Jest/JSDom don't know about TextEncoder but the browsers we support do
// https://github.com/jsdom/jsdom/issues/2524
global.TextDecoder = TextDecoder
global.TextEncoder = TextEncoder

window.scrollTo = jest.fn()
window.matchMedia = jest.fn(
    () => ({ matches: false, addListener: jest.fn(), removeListener: jest.fn() } as MediaQueryList)
)
