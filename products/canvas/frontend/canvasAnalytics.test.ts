import { canvasErrorType } from './canvasAnalytics'

describe('canvasErrorType', () => {
    it.each([
        ['TypeError: cannot read a property', 'TypeError'],
        ['RangeError: invalid length', 'RangeError'],
        ['Error: example failure', 'Error'],
        ['ExamplePrivateValueError: failed', 'unknown'],
        ['ExamplePrivateValueError', 'unknown'],
        ['TypeErrorWithPrivateSuffix', 'unknown'],
        ['failed to render', 'unknown'],
    ])('classifies %s without copying custom identifiers', (message, expected) => {
        expect(canvasErrorType(message)).toBe(expected)
    })
})
