import 'whatwg-fetch'
import 'jest-canvas-mock'

window.scrollTo = jest.fn()
window.matchMedia = jest.fn(
    () => ({ matches: false, addListener: jest.fn(), removeListener: jest.fn() } as MediaQueryList)
)
