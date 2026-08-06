import { shouldCaptureLoaderError } from './initKea'

describe('shouldCaptureLoaderError', () => {
    it.each<[string, string, number, boolean]>([
        ['an expected fingerprint resolution miss', 'resolveFingerprint', 404, false],
        ['an unexpected fingerprint resolution failure', 'resolveFingerprint', 500, true],
        ['an unrelated 404', 'loadSomethingElse', 404, true],
    ])('captures %s: %s', (_name, actionKey, status, expected) => {
        expect(shouldCaptureLoaderError(actionKey, { status })).toBe(expected)
    })
})
