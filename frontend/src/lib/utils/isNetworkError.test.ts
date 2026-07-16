import { ApiError } from 'lib/api-error'
import { isNetworkError } from 'lib/utils/isNetworkError'

describe('isNetworkError', () => {
    // handleFetch rewraps a fetch-level throw into an ApiError with no status, stringifying the
    // browser-native TypeError message. These are the shapes that reach a loader's catch block.
    const cases: [string, unknown, boolean][] = [
        ['raw Chromium TypeError', new TypeError('Failed to fetch'), true],
        ['wrapped Chromium failure', new ApiError(new TypeError('Failed to fetch') as any), true],
        [
            'wrapped Firefox failure',
            new ApiError(new TypeError('NetworkError when attempting to fetch resource.') as any),
            true,
        ],
        ['wrapped Safari failure', new ApiError(new TypeError('Load failed') as any), true],
        ['real API error with status', new ApiError('Not found', 404), false],
        ['unrelated error', new Error('Something else broke'), false],
        ['null', null, false],
        ['string', 'Failed to fetch', false],
    ]

    it.each(cases)('%s -> %s', (_desc, error, expected) => {
        expect(isNetworkError(error)).toBe(expected)
    })
})
