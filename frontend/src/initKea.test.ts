import { shouldCaptureLoaderError } from './initKea'

describe('shouldCaptureLoaderError', () => {
    it.each([
        // [description, error, actionKey, expected]
        [
            'statusless network failure (Failed to fetch) on an allow-listed action',
            { status: undefined },
            'loadRecordingMeta',
            false,
        ],
        ['statusless network failure on a non-allow-listed action', { status: undefined }, 'loadDashboard', false],
        ['error object with no status field at all', {}, 'loadDashboard', false],
        ['null error', null, 'loadDashboard', false],
        ['transient gateway 502', { status: 502 }, 'loadDashboard', false],
        ['transient gateway 503', { status: 503 }, 'loadDashboard', false],
        ['transient gateway 504', { status: 504 }, 'loadDashboard', false],
        ['allow-listed action with a real status', { status: 500 }, 'loadRecordingMeta', false],
        ['genuine backend exception (500) on a non-allow-listed action', { status: 500 }, 'loadDashboard', true],
        ['application error (400) on a non-allow-listed action', { status: 400 }, 'loadDashboard', true],
        ['not found (404) on a non-allow-listed action', { status: 404 }, 'loadDashboard', true],
    ])('returns expected for %s', (_description, error, actionKey, expected) => {
        expect(shouldCaptureLoaderError(error, actionKey as string)).toBe(expected)
    })
})
